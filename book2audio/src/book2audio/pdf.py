"""PDF ingestion.

pypdf reads the bookmarks and metadata, pdfminer.six reads text with positions. Both are
permissively licensed; PyMuPDF is AGPL-3.0 and is deliberately not used.

From positions and font sizes this module removes running headers and footers, page numbers,
footnotes and footnote markers, rebuilds paragraphs, and repairs hyphenated line ends. Chapters
come from the bookmarks, or from headings when there are none. A PDF with no text layer is run
through ocrmypdf if it is installed, otherwise reported clearly.
"""
import os
import re
import shutil
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import LAParams, LTAnno, LTChar, LTTextContainer, LTTextLine
from pypdf import PdfReader

from .book import B2AError, Book, Chapter, skip_reason

HEADING_SCALE = 1.25      # a line this much bigger than body text is a heading
FOOTNOTE_SCALE = 0.85     # a line this much smaller, low on the page, is a footnote
MARKER_SCALE = 0.75       # a digit or symbol this small is a footnote marker
EDGE = 0.10               # top and bottom 10% of a page hold headers and footers
MIN_CHARS_PER_PAGE = 40   # fewer sampled characters per page than this means "no text layer"
PART_CHARS = 40_000       # a heading-less book is cut into parts about this long
# A sentence ends at . ! ? … or : (followed by any closing quotes or brackets). A line that stops
# anywhere else, even on a closing quote like  "Hello,"  is mid-sentence.
SENTENCE_END = re.compile(r"[.!?…:][\"'”’)\]»]*$")
PAGE_NUMBER = re.compile(r"^(page\s+)?(\d+|[ivxlc]+)(\s+of\s+\d+)?$", re.I)
HEADING = re.compile(r"^(chapter|part|book|section)\s+(\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)\b"
                     r"|^(prologue|epilogue|preface|introduction|foreword|afterword)\b", re.I)


@dataclass
class Line:
    page: int
    box: int
    x0: float
    x1: float
    y0: float
    y1: float
    chars: list  # [(text, font size or None for pdfminer's spacing marks)]


@dataclass
class Para:
    text: str
    heading: bool
    page: int
    lines: int = field(default=1, repr=False)


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _is_scanned(path, npages) -> bool:
    """True when sampled pages hold almost no extractable text, i.e. they are pictures."""
    sample = sorted({round(i * (npages - 1) / 7) for i in range(8)}) if npages > 1 else [0]
    chars = sum(len("".join(extract_text(str(path), page_numbers=[p]).split())) for p in sample)
    return chars / len(sample) < MIN_CHARS_PER_PAGE


def _ocr(path: Path, work_dir: Path, log) -> Path:
    exe = shutil.which("ocrmypdf")
    if not exe:
        raise B2AError(f"{path.name} looks scanned (no text layer), so it needs OCR. Install ocrmypdf and "
                       "tesseract (pip install ocrmypdf, plus the tesseract program) and run again, or "
                       "supply an EPUB or a text-based PDF.")
    out = work_dir / "ocr.pdf"
    if not out.exists():  # reruns reuse the OCR result
        log(f"{path.name} looks scanned: running OCR with ocrmypdf (English; this can take a long time)")
        work_dir.mkdir(parents=True, exist_ok=True)
        tmp = work_dir / "ocr.partial.pdf"
        r = subprocess.run([exe, "--skip-text", "--quiet", str(path), str(tmp)], capture_output=True, text=True)
        if r.returncode:
            raise B2AError(f"ocrmypdf failed: {r.stderr.strip()[-300:]}")
        os.replace(tmp, out)
    return out


def _read_lines(path, log) -> tuple[list[Line], list[float]]:
    lines, heights = [], []
    for pno, page in enumerate(extract_pages(str(path), laparams=LAParams())):
        heights.append(page.height)
        boxes = [b for b in page if isinstance(b, LTTextContainer)]
        for bno, box in enumerate(boxes):
            for ln in box:
                if not isinstance(ln, LTTextLine):
                    continue
                chars = [(o.get_text(), o.size) if isinstance(o, LTChar) else (" ", None)
                         for o in ln if isinstance(o, (LTChar, LTAnno))]
                lines.append(Line(pno, bno, ln.x0, ln.x1, ln.y0, ln.y1, chars))
        if (pno + 1) % 25 == 0:
            log(f"  read {pno + 1} pages")
    return lines, heights


def _body_size(lines) -> float:
    sizes = Counter(round(s, 1) for l in lines for c, s in l.chars if s and c.strip())
    return sizes.most_common(1)[0][0] if sizes else 10.0


def _text(l: Line, body: float) -> str:
    """Line text without footnote markers (tiny digits and symbols)."""
    keep = (c for c, s in l.chars if not (s and s < body * MARKER_SCALE and c in "0123456789*†‡§"))
    return " ".join("".join(keep).split())


def _size(l: Line, body: float) -> float:
    sizes = [s for c, s in l.chars if s and c.strip()]
    return statistics.median(sizes) if sizes else body


def _furniture(lines, heights, body, text) -> set[int]:
    """ids of lines that are running headers, footers, page numbers or footnotes."""
    edge = [l for l in lines if l.y1 > heights[l.page] * (1 - EDGE) or l.y0 < heights[l.page] * EDGE]
    key = lambda l: re.sub(r"\d+", "#", text(l).lower())  # noqa: E731  ("Page 12" and "Page 13" match)
    pages_with = defaultdict(set)
    for l in edge:
        pages_with[key(l)].add(l.page)
    need = 3 if len(heights) >= 15 else 2
    drop = set()
    for l in edge:
        t = text(l)
        if PAGE_NUMBER.match(t) or len(pages_with[key(l)]) >= need:
            drop.add(id(l))
    for l in lines:  # footnotes: small text in the lower part of the page
        if l.y1 < heights[l.page] * 0.4 and _size(l, body) < body * FOOTNOTE_SCALE:
            drop.add(id(l))
    return drop


def _join(acc: str, nxt: str) -> str:
    acc = acc.replace("\xad", "")
    if acc.endswith("-"):
        # "exam-" + "ple" -> "example". shortcut: "well-" + "known" also loses its hyphen;
        # a dictionary check would fix that, add one if real books show it.
        return acc[:-1] + nxt if nxt[:1].islower() else acc + nxt
    return f"{acc} {nxt}"


def _paragraphs(lines, heights, body, drop, text) -> list[Para]:
    by_page = defaultdict(list)
    for l in lines:
        if id(l) not in drop and text(l):
            by_page[l.page].append(l)
    paras: list[Para] = []
    cur: Para | None = None
    prev: Line | None = None
    for pno in sorted(by_page):
        kept = by_page[pno]
        left, right = min(l.x0 for l in kept), max(l.x1 for l in kept)
        for l in kept:
            t = text(l)
            head = _size(l, body) >= body * HEADING_SCALE and len(t) < 100
            if cur is None or head != cur.heading:
                new = True
            elif head:
                new = prev is None or l.page != prev.page  # a heading's lines stay together on their page
            else:
                same_box = prev is not None and l.page == prev.page and l.box == prev.box
                ended = bool(SENTENCE_END.search(cur.text))
                indented = l.x0 - left > body * 0.8
                short_prev = prev is not None and l.page == prev.page and prev.x1 < right - 0.2 * (right - left)
                if not same_box:  # another layout box or page: continue unless a sentence finished or a new indent starts
                    new = indented or ended
                else:
                    new = indented or (short_prev and ended)
            if new:
                cur = Para(t, head, pno)
                paras.append(cur)
            else:
                cur.text = _join(cur.text, t)
            prev = l
    return paras


def _outline(reader) -> list[tuple[str, int]]:
    """Bookmarks at the shallowest level that has at least three entries -> [(title, page)]."""
    found = []

    def walk(items, level):
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(it)
            except Exception:  # broken destination; skip that bookmark
                continue
            if page is not None and page >= 0 and (it.title or "").strip():
                found.append((" ".join(it.title.split()), page, level))

    try:
        walk(reader.outline, 0)
    except Exception:  # a damaged outline tree is no reason to stop
        return []
    counts = Counter(l for _, _, l in found)
    level = next((l for l in sorted(counts) if counts[l] >= 3), None)
    if level is None:
        return []
    picked = sorted({p: t for t, p, l in reversed(found) if l == level}.items())  # one chapter per page
    return [(t, p) for p, t in picked]


def _strip_title(paras: list[str], title: str) -> list[str]:
    """Drop the leading paragraphs that just spell out the chapter title."""
    norm = lambda s: re.sub(r"\W+", "", s).lower()  # noqa: E731
    want, acc, used = norm(title), "", 0
    for p in paras[:4]:
        if not want.startswith(acc + norm(p)):
            break
        acc, used = acc + norm(p), used + 1
        if acc == want:
            return paras[used:]
    return paras


def _chapters(paras: list[Para], outline, book_title: str) -> list[Chapter]:
    if outline:
        starts = [(t, p) for t, p in outline]
        groups = []
        for n, (title, page) in enumerate(starts):
            end = starts[n + 1][1] if n + 1 < len(starts) else 10 ** 9
            groups.append((title, [p.text for p in paras if page <= p.page < end]))
    else:
        groups, title, body, title_page = [], None, [], -1
        for p in paras:
            if p.heading or (len(p.text) < 80 and HEADING.match(p.text)):
                if title is not None and not body and p.page == title_page:  # "CHAPTER I." then its subtitle
                    title = f"{title} {p.text}"
                    continue
                if title is not None:
                    groups.append((title, body))
                title, body, title_page = p.text, [], p.page
            elif title is not None:
                body.append(p.text)
        if title is not None:
            groups.append((title, body))
        groups = [g for g in groups if len(g[1]) > 0]
        if len(groups) < 2:  # no usable headings: cut the book into parts so it still gets chapter marks
            groups = _parts([p.text for p in paras], book_title)
    out = []
    for title, body in groups:
        body = _strip_title(body, title)
        text = "\n\n".join(body)
        out.append(Chapter(title, text, skip_reason(title, text)))
    return out


def _parts(texts: list[str], title: str):
    parts, cur, size = [], [], 0
    for t in texts:
        if cur and size + len(t) > PART_CHARS:
            parts.append(cur)
            cur, size = [], 0
        cur.append(t)
        size += len(t)
    if cur:
        parts.append(cur)
    return [(f"{title}, part {n + 1}" if len(parts) > 1 else title, p) for n, p in enumerate(parts)]


def load(path, work_dir=None, log=_log) -> Book:
    path = Path(path)
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise B2AError(f"{path.name} is password-protected; remove the password first")
        npages = len(reader.pages)
    except B2AError:
        raise
    except Exception as e:
        raise B2AError(f"cannot read {path} as a PDF: {e}")
    if npages == 0:
        raise B2AError(f"{path.name} has no pages")
    meta = reader.metadata
    title = " ".join(((meta.title if meta else None) or path.stem).split())
    author = " ".join(((meta.author if meta else None) or "").split())

    src = path
    if _is_scanned(path, npages):
        src = _ocr(path, Path(work_dir or path.parent), log)
        reader = PdfReader(str(src))
    log(f"reading {npages} pages of {path.name}")
    lines, heights = _read_lines(src, log)
    if not lines:
        raise B2AError(f"no text could be read from {path.name}")
    body = _body_size(lines)
    text = lambda l: _text(l, body)  # noqa: E731
    paras = _paragraphs(lines, heights, body, _furniture(lines, heights, body, text), text)
    return Book(title, author, _chapters(paras, _outline(reader), title))
