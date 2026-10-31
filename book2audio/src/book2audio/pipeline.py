"""The pipeline stages and the job directory.

A job directory holds everything a run produces:

    job.json            which source file this job belongs to (a different book is refused)
    text/NN.txt         the exact text each chapter is read from
    llm/<hash>.txt      Claude-pass results, per segment
    tts/<backend>/...   synthesized chunks, named by content hash
    chapters/NN-*.m4a   finished chapters
    m4b/                scratch files for the final assembly

Every stage is keyed by content, so re-running the same command picks up where it stopped
and never pays twice for a chunk.
"""
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import assemble, epub, llm, pdf
from .book import B2AError, Book, Cancelled, Chapter
from .chunk import chunk
from .normalize import normalize, normalize_paragraph, sentence_end
from .tts import Backend, synth_cached


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# Long runs report to a `progress(event: dict)` callback (the web page uses it) and stop when `cancel.is_set()`
# (a threading.Event). Both are optional; the CLI passes neither and keeps using `log`.
def _emit(progress, **event):
    if progress:
        progress(event)


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


@dataclass
class Prepared:
    number: int   # 1-based position among the narrated chapters
    title: str
    text: str     # exactly what is spoken: the title first, then the chapter


class Job:
    def __init__(self, root, source: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with open(source, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
        manifest = self.root / "job.json"
        if manifest.exists():
            if json.loads(manifest.read_text(encoding="utf-8")).get("source_sha256") != digest.hexdigest():
                raise B2AError(f"{self.root} holds a job for a different file than {source.name}; "
                               "pick another --job-dir (or delete that folder to start over)")
        else:
            manifest.write_text(json.dumps({"source": source.name, "source_sha256": digest.hexdigest()}, indent=2),
                                encoding="utf-8")
        self.text, self.llm, self.tts = self.root / "text", self.root / "llm", self.root / "tts"
        self.chapters, self.m4b = self.root / "chapters", self.root / "m4b"


def load_book(path: Path, job: Job) -> Book:
    kind = path.suffix.lower()
    if kind == ".epub":
        return epub.load(path)
    if kind == ".pdf":
        return pdf.load(path, work_dir=job.root, log=log)
    raise B2AError(f"{path.name}: only .epub and .pdf files are supported")


def parse_range(spec: str, n: int) -> list[int]:
    """'1-3,5' -> [1, 2, 3, 5], checked against the n chapters that exist."""
    picked = []
    try:
        for part in spec.split(","):
            a, _, b = part.strip().partition("-")
            picked += range(int(a), int(b or a) + 1)
    except ValueError:
        raise B2AError(f"--chapters {spec!r}: use numbers and ranges such as 1-3,5")
    if not picked or min(picked) < 1 or max(picked) > n:
        raise B2AError(f"--chapters {spec!r}: this book has {n} chapters to narrate (numbered 1 to {n})")
    return sorted(set(picked))


def select(book: Book, spec=None, keep_all=False) -> tuple[list[tuple[int, Chapter]], list[Chapter]]:
    """-> ([(number, chapter)] to narrate, [skipped chapters]). Numbers count narrated chapters only."""
    kept = [c for c in book.chapters if c.text.strip() and (keep_all or not c.skip)]
    skipped = [c for c in book.chapters if c not in kept]
    numbered = list(enumerate(kept, 1))
    if spec:
        wanted = set(parse_range(spec, len(kept)))
        numbered = [(n, c) for n, c in numbered if n in wanted]
    return numbered, skipped


def rule_text(ch: Chapter) -> str:
    """What is spoken for a chapter by rules alone (no Claude pass): the title, then the normalized text."""
    return sentence_end(normalize_paragraph(ch.title)) + "\n\n" + normalize(ch.text)


def prepare(picks, job: Job, llm_opts=None, log=log, progress=None, cancel=None, save=True) -> list[Prepared]:
    """Rule-normalize each chapter (and run the Claude pass when llm_opts is given); write text/NN.txt."""
    if save:
        job.text.mkdir(parents=True, exist_ok=True)
    out = []
    for index, (number, ch) in enumerate(picks, 1):
        _check(cancel)
        if llm_opts:
            _emit(progress, stage="text", index=index, count=len(picks), title=ch.title)
            log(f"Claude pass ({llm_opts['mode']}) on chapter {number}: {ch.title}")
            body = normalize(ch.text)
            body = normalize(llm.process(body, llm_opts["mode"], llm_opts["model"], job.llm, llm_opts["client"],
                                         llm_opts["condense"], log))
            text = sentence_end(normalize_paragraph(ch.title)) + "\n\n" + body
        else:
            text = rule_text(ch)
        if save:
            (job.text / f"{number:02d}.txt").write_text(text, encoding="utf-8")
        out.append(Prepared(number, ch.title, text))
    return out


def sample_text(text: str, low=100, high=200) -> str:
    """About one to two sentences from the start of a (normalized) chapter, for a voice sample."""
    body = text.split("\n\n", 1)[-1]  # the chapter title comes first and says little about the voice
    pieces = chunk(body, high)
    return next((c for c in pieces if len(c) >= low), pieces[0] if pieces else "")


def synthesize(prepared: list[Prepared], backend: Backend, job: Job, log=log, progress=None, cancel=None) -> list[Path]:
    """Chunk, synthesize (cached) and build one AAC file per chapter."""
    chunked = [chunk(p.text, backend.max_chars) for p in prepared]
    total, done, files = sum(len(c) for cs in chunked for c in cs), 0, []
    for index, (p, chunks) in enumerate(zip(prepared, chunked), 1):
        where = dict(index=index, count=len(prepared), title=p.title)
        audio = []
        for i, c in enumerate(chunks):
            _check(cancel)  # a chunk in flight finishes and is cached, so stopping never wastes a paid call
            path, hit = synth_cached(backend, c, job.tts, chunks[i - 1] if i else "",
                                     chunks[i + 1] if i + 1 < len(chunks) else "")
            done += len(c)
            log(f"[{p.number}/{prepared[-1].number}] {p.title[:40]!r} chunk {i + 1}/{len(chunks)}: "
                f"{'cached' if hit else 'synthesized'}")
            _emit(progress, stage="voice", chunk=i + 1, chunks=len(chunks), cached=hit, done=done, total=total,
                  **where)
            audio.append(path)
        key = hashlib.sha256("\n".join(a.name for a in audio).encode() + assemble.LOUDNESS.encode()).hexdigest()[:12]
        out = job.chapters / f"{p.number:02d}-{key}.m4a"
        if not out.exists():
            _check(cancel)
            log(f"[{p.number}/{prepared[-1].number}] mixing chapter")
            _emit(progress, stage="mix", done=done, total=total, **where)
            assemble.build_chapter(audio, out)
        files.append(out)
    return files


def convert(book: Book, picks, backend: Backend, job: Job, out: Path, llm_opts=None, log=log, progress=None,
            cancel=None) -> float:
    """The whole run: text, voice, chapters, then the .m4b at `out`. -> its length in seconds."""
    prepared = prepare(picks, job, llm_opts, log, progress, cancel)
    files = synthesize(prepared, backend, job, log, progress, cancel)
    _check(cancel)
    _emit(progress, stage="book")
    return assemble.build_m4b(files, [p.title for p in prepared], Path(out), book.title, book.author,
                              book.cover, book.cover_ext, work=job.m4b)
