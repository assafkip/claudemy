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
from .book import B2AError, Book, Chapter
from .chunk import chunk
from .normalize import normalize, normalize_paragraph, sentence_end
from .tts import Backend, synth_cached


def log(msg):
    print(msg, file=sys.stderr, flush=True)


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


def prepare(picks, job: Job, llm_opts=None, log=log) -> list[Prepared]:
    """Rule-normalize each chapter (and run the Claude pass when llm_opts is given); write text/NN.txt."""
    job.text.mkdir(parents=True, exist_ok=True)
    out = []
    for number, ch in picks:
        body = normalize(ch.text)
        if llm_opts:
            log(f"Claude pass ({llm_opts['mode']}) on chapter {number}: {ch.title}")
            body = normalize(llm.process(body, llm_opts["mode"], llm_opts["model"], job.llm, llm_opts["client"],
                                         llm_opts["condense"], log))
        text = sentence_end(normalize_paragraph(ch.title)) + "\n\n" + body
        (job.text / f"{number:02d}.txt").write_text(text, encoding="utf-8")
        out.append(Prepared(number, ch.title, text))
    return out


def synthesize(prepared: list[Prepared], backend: Backend, job: Job, log=log) -> list[Path]:
    """Chunk, synthesize (cached) and build one AAC file per chapter."""
    files = []
    for p in prepared:
        chunks = chunk(p.text, backend.max_chars)
        audio = []
        for i, c in enumerate(chunks):
            path, hit = synth_cached(backend, c, job.tts, chunks[i - 1] if i else "",
                                     chunks[i + 1] if i + 1 < len(chunks) else "")
            log(f"[{p.number}/{prepared[-1].number}] {p.title[:40]!r} chunk {i + 1}/{len(chunks)}: "
                f"{'cached' if hit else 'synthesized'}")
            audio.append(path)
        key = hashlib.sha256("\n".join(a.name for a in audio).encode() + assemble.LOUDNESS.encode()).hexdigest()[:12]
        out = job.chapters / f"{p.number:02d}-{key}.m4a"
        if not out.exists():
            log(f"[{p.number}/{prepared[-1].number}] mixing chapter")
            assemble.build_chapter(audio, out)
        files.append(out)
    return files
