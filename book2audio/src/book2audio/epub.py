"""EPUB ingestion.

The package (OPF, nav, NCX) is read with zipfile + ElementTree and the pages with
BeautifulSoup. ebooklib is deliberately not used: it is AGPL-3.0 and this project is MIT.

Chapters come from the table of contents. A TOC entry can point into the middle of a page
(file.xhtml#id), so pages are split into paragraphs that remember the ids they contain and
each chapter runs from its entry to the next one.
"""
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from bisect import bisect_left
from urllib.parse import unquote, urldefrag

from bs4 import BeautifulSoup, NavigableString, Tag

from .book import B2AError, Book, Chapter, skip_reason

NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container",
      "o": "http://www.idpf.org/2007/opf",
      "dc": "http://purl.org/dc/elements/1.1/",
      "n": "http://www.daisy.org/z3986/2005/ncx/"}
SKIP_TAGS = {"script", "style", "head", "title", "nav", "svg", "audio", "video"}
# Footnote bodies, note markers and page-break markers are not read aloud.
SKIP_TYPES = {"footnote", "footnotes", "endnote", "endnotes", "rearnote", "rearnotes", "noteref", "pagebreak",
              "doc-footnote", "doc-endnote", "doc-noteref", "doc-pagebreak"}
# epub:type values that mark a whole page as front or back matter.
MATTER_TYPES = {"frontmatter", "backmatter", "copyright-page", "titlepage", "halftitlepage", "toc", "colophon",
                "index", "loi", "lot"}
BLOCK = {"p", "div", "section", "article", "aside", "blockquote", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2",
         "h3", "h4", "h5", "h6", "header", "footer", "main", "body", "html", "figcaption", "hr", "address"}
CODE_LINE = "There is a code listing here, which is not read aloud."
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif"}


def _clean(s: str) -> str:
    return " ".join(s.split())


def _types(el: Tag) -> set[str]:
    return set((el.get("epub:type") or "").split()) | set((el.get("role") or "").split())


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _describe_table(t: Tag) -> str:
    rows = t.find_all("tr")
    cols = max((len(r.find_all(["td", "th"])) for r in rows), default=0)
    head = [_clean(c.get_text(" "))[:30] for c in (rows[0].find_all(["th", "td"]) if rows else [])]
    head = [h for h in head if h][:5]
    covering = f", covering {', '.join(head)}" if head else ""
    return f"There is a table here with {_plural(len(rows), 'row')} and {_plural(cols, 'column')}{covering}."


def _describe_figure(f: Tag) -> str:
    cap = f.find("figcaption")
    img = f.find("img")
    alt = (img.get("alt") or "").strip() if img else ""
    what = _clean(cap.get_text(" ")) if cap else alt
    return f"There is a figure here: {what.rstrip('.')}." if what else "There is a figure here."


class _Paragraphs:
    """Collects paragraph text, and the element ids seen on the way to each paragraph."""

    def __init__(self):
        self.out: list[tuple[str, set[str]]] = []
        self.buf: list[str] = []
        self.ids: set[str] = set()

    def mark(self, el: Tag):
        i = el.get("id") or (el.get("name") if el.name == "a" else None)
        if i:
            self.ids.add(i)

    def flush(self):
        text = _clean("".join(self.buf))
        self.buf = []
        if text:  # ids stay pending across empty flushes and land on the next paragraph
            self.out.append((text, self.ids))
            self.ids = set()

    def finish(self):
        self.flush()
        if self.ids:  # a TOC target whose content was skipped, e.g. the licence block at the end of a page
            self.out.append(("", self.ids))

    def add(self, text: str):
        self.flush()
        self.buf = [text]
        self.flush()


def _walk(el: Tag, p: _Paragraphs):
    for c in el.children:
        if type(c) is NavigableString:  # not Comment, Doctype, CData...
            p.buf.append(str(c))
            continue
        if not isinstance(c, Tag):
            continue
        p.mark(c)  # even a skipped element can be a TOC target
        name = c.name
        if name in SKIP_TAGS or _types(c) & SKIP_TYPES or "pg-boilerplate" in (c.get("class") or []):
            for inner in c.find_all(True):
                p.mark(inner)
            continue
        if name == "sup" and c.find("a", href=re.compile(r"^#")):  # footnote call in a superscript
            continue
        if name == "table":
            p.add(_describe_table(c))
        elif name == "pre":
            p.add(CODE_LINE)
        elif name == "figure":
            p.add(_describe_figure(c))
        elif name == "img":
            alt = (c.get("alt") or "").strip()
            if alt:
                p.add(f"Image: {alt.rstrip('.')}.")
        elif name == "br":
            p.buf.append(" ")
        elif name in BLOCK:
            p.flush()
            _walk(c, p)
            p.flush()
        else:
            _walk(c, p)


def page_paragraphs(html: bytes) -> tuple[list[tuple[str, set[str]]], set[str]]:
    """One page -> ([(paragraph text, ids)], epub:type values on the body and its children)."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body") or soup
    types: set[str] = set()
    if isinstance(body, Tag):
        for el in [body, *body.find_all(recursive=False)]:
            types |= _types(el)
    p = _Paragraphs()
    _walk(body, p)
    p.finish()
    return p.out, types


def _target(base: str, href: str) -> tuple[str, str]:
    path, frag = urldefrag(href)
    full = base if not path else posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(path)))
    return full, unquote(frag)


def _nav_entries(html: bytes, path: str) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    nav = next((n for n in soup.find_all("nav") if "toc" in (n.get("epub:type") or "").split()), None) \
        or soup.find("nav")
    if nav is None:
        return []
    return [(_clean(a.get_text(" ")), *_target(path, a["href"])) for a in nav.find_all("a", href=True)]


def _ncx_entries(xml: bytes, path: str) -> list[tuple[str, str, str]]:
    out = []
    for np in ET.fromstring(xml).iter(f"{{{NS['n']}}}navPoint"):  # pre-order = reading order
        label = np.findtext("n:navLabel/n:text", default="", namespaces=NS)
        content = np.find("n:content", NS)
        if content is not None and content.get("src"):
            out.append((_clean(label), *_target(path, content.get("src"))))
    return out


def load(path) -> Book:
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise B2AError(f"cannot open {path} as an EPUB: {e}")
    with z:
        try:
            opf_path = ET.fromstring(z.read("META-INF/container.xml")).find(".//c:rootfile", NS).get("full-path")
            opf = ET.fromstring(z.read(opf_path))
        except (KeyError, AttributeError, ET.ParseError) as e:
            raise B2AError(f"{path} is not a valid EPUB (package file unreadable: {e})")
        base = posixpath.dirname(opf_path)

        def full(href):
            return posixpath.normpath(posixpath.join(base, unquote(href)))

        manifest = {i.get("id"): i for i in opf.findall("o:manifest/o:item", NS)}
        spine = [manifest[r.get("idref")] for r in opf.findall("o:spine/o:itemref", NS) if r.get("idref") in manifest]
        spine = [i for i in spine if "html" in i.get("media-type", "") or i.get("media-type", "").endswith("xml")]
        if not spine:
            raise B2AError(f"{path} has no readable pages in its spine")

        title = _clean(opf.findtext("o:metadata/dc:title", default="", namespaces=NS)) or "Untitled"
        author = ", ".join(_clean(a.text or "") for a in opf.findall("o:metadata/dc:creator", NS) if a.text)

        # TOC: EPUB 3 nav document first, then the EPUB 2 NCX.
        nav = next((i for i in manifest.values() if "nav" in (i.get("properties") or "").split()), None)
        ncx = manifest.get(opf.find("o:spine", NS).get("toc"))
        if ncx is None:  # (an Element with no children is falsy, so never `a or b` on Elements)
            ncx = next((i for i in manifest.values() if i.get("media-type") == "application/x-dtbncx+xml"), None)
        entries = []
        if nav is not None:
            entries = _nav_entries(z.read(full(nav.get("href"))), full(nav.get("href")))
        if not entries and ncx is not None:
            entries = _ncx_entries(z.read(full(ncx.get("href"))), full(ncx.get("href")))

        pages = []  # (path, paragraphs, types)
        for item in spine:
            name = full(item.get("href"))
            try:
                paras, types = page_paragraphs(z.read(name))
            except KeyError:
                continue
            pages.append((name, paras, types))

        cover, ext = _cover(z, opf, manifest, full)
    chapters = _chapters(pages, entries)
    return Book(title, author, chapters, cover, ext)


def _cover(z, opf, manifest, full):
    cid = next((m.get("content") for m in opf.findall("o:metadata/o:meta", NS) if m.get("name") == "cover"), None)
    item = manifest.get(cid)
    if item is None:
        item = next((i for i in manifest.values() if "cover-image" in (i.get("properties") or "").split()), None)
    if item is None or item.get("media-type") not in IMAGE_TYPES:
        return None, "jpg"
    try:
        return z.read(full(item.get("href"))), IMAGE_TYPES[item.get("media-type")]
    except KeyError:
        return None, "jpg"


def _chapters(pages, entries) -> list[Chapter]:
    keys, texts = [], []  # global paragraph order: (page index, paragraph index)
    for d, (_, paras, _) in enumerate(pages):
        for i, (text, _) in enumerate(paras):
            keys.append((d, i))
            texts.append(text)
    page_of = {name: d for d, (name, _, _) in enumerate(pages)}

    starts: dict[tuple[int, int], str] = {}  # position -> title; a later entry at the same spot wins
    for label, path, frag in entries:
        d = page_of.get(path)
        if d is None or not label:
            continue
        i = next((n for n, (_, ids) in enumerate(pages[d][1]) if frag and frag in ids), 0)
        starts[(d, i)] = label
    if not starts:  # no usable TOC: one chapter per page, named after its first short paragraph
        for d, (_, paras, _) in enumerate(pages):
            if paras:
                first = paras[0][0]
                starts[(d, 0)] = first if len(first) < 80 else f"Section {len(starts) + 1}"

    out = []
    order = sorted(starts)
    for n, pos in enumerate(order):
        a = bisect_left(keys, pos)
        b = bisect_left(keys, order[n + 1]) if n + 1 < len(order) else len(keys)
        body = [t for t in texts[a:b] if t]
        title = starts[pos]
        norm = lambda s: re.sub(r"\W+", "", s).lower()  # noqa: E731
        if body and norm(body[0]) == norm(title):  # the heading is spoken as the title
            body = body[1:]
        text = "\n\n".join(body)
        reason = skip_reason(title, text)
        page_types = pages[pos[0]][2]
        if reason is None and page_types & MATTER_TYPES:
            reason = f"front/back matter (epub:type {sorted(page_types & MATTER_TYPES)[0]})"
        out.append(Chapter(title, text, reason))
    return out
