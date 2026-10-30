"""book2audio command line."""
import argparse
import os
import sys
from pathlib import Path

from . import __version__, assemble, estimate, llm, pipeline
from .book import B2AError
from .tts import BACKENDS, make_backend

COVER_TYPES = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png"}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="book2audio", description="Convert an .epub or .pdf book into a chaptered "
                                ".m4b audiobook. Run with --dry-run first: it shows chapters, size, time and cost "
                                "and synthesizes nothing.")
    p.add_argument("input", help="the .epub or .pdf file")
    p.add_argument("-o", "--output", help="output .m4b (default: next to the input)")
    p.add_argument("--job-dir", help="working folder; run the same command again to resume (default: <input>.b2a)")
    p.add_argument("--dry-run", action="store_true", help="print chapters, characters and estimates; do nothing else")
    p.add_argument("--yes", action="store_true", help="confirm a paid run (ElevenLabs, or --llm) after reading "
                                                      "the estimate")
    p.add_argument("--backend", choices=list(BACKENDS), default="piper", help="voice engine (default: piper, free)")
    p.add_argument("--voice", help="voice id (elevenlabs), voice name or .onnx path (piper), voice name (say), e.g. en-US-Chirp3-HD-Charon (google)")
    p.add_argument("--model", help="ElevenLabs model id (default: eleven_multilingual_v2)")
    p.add_argument("--mode", choices=["faithful", "adapted"], default="faithful",
                   help="faithful: read the text as written (default). adapted: Claude rewrites it as narration "
                        "(needs --llm)")
    p.add_argument("--llm", action="store_true", help="run the Claude pass (sends the text to Anthropic; paid)")
    p.add_argument("--llm-model", default=llm.DEFAULT_MODEL, help=f"Claude model (default: {llm.DEFAULT_MODEL})")
    p.add_argument("--condense", action="store_true", help="with --mode adapted: about half the length")
    p.add_argument("--chapters", help="narrate only these chapters, e.g. 1-3,5 (numbers as in the dry-run list)")
    p.add_argument("--keep-all", action="store_true", help="also narrate front/back matter and short sections")
    p.add_argument("--cover", help="cover image (.jpg or .png); default: the book's own cover when it has one")
    p.add_argument("--title", help="override the book title")
    p.add_argument("--author", help="override the author")
    p.add_argument("--price-per-1k", type=float, default=os.environ.get("BOOK2AUDIO_PRICE_PER_1K"),
                   help="your price for 1,000 ElevenLabs credits or Google characters, to show money in the estimate")
    p.add_argument("--version", action="version", version=f"book2audio {__version__}")
    return p


def run(args) -> int:
    if args.mode == "adapted" and not args.llm:
        raise B2AError("--mode adapted needs --llm: Claude does the rewriting")
    if args.condense and args.mode != "adapted":
        raise B2AError("--condense only applies with --mode adapted")
    src = Path(args.input)
    if not src.is_file():
        raise B2AError(f"no such file: {src}")
    price = args.price_per_1k

    job = pipeline.Job(args.job_dir or src.parent / f"{src.stem}.b2a", src)
    book = pipeline.load_book(src, job)
    book.title, book.author = args.title or book.title, args.author or book.author
    if args.cover:
        cover = Path(args.cover)
        if cover.suffix.lower() not in COVER_TYPES or not cover.is_file():
            raise B2AError("--cover must be an existing .jpg or .png file")
        book.cover, book.cover_ext = cover.read_bytes(), COVER_TYPES[cover.suffix.lower()]

    picks, skipped = pipeline.select(book, args.chapters, args.keep_all)
    if not picks:
        raise B2AError(f"nothing to narrate: all {len(book.chapters)} sections look like front/back matter or are "
                       "empty (try --keep-all)")
    backend = make_backend(args.backend, args.voice, args.model)
    llm_opts = {"mode": args.mode, "model": args.llm_model, "condense": args.condense, "client": None} \
        if args.llm else None

    prepared = pipeline.prepare(picks, job)  # rules only: free and local
    print(estimate.report(book, prepared, skipped, job, backend, f"{src.name} ({src.suffix[1:].upper()})",
                          llm_opts, price, dry_run=args.dry_run))
    if args.dry_run:
        return 0

    # Check everything that can fail before anything is spent.
    backend.check()
    assemble.require_ffmpeg()
    if llm_opts:
        llm_opts["client"] = llm.make_client()
    if (backend.paid or args.llm) and not args.yes:
        print("\nThis run uses a paid service. Read the estimate above, then run the same command again with "
              "--yes to start.", file=sys.stderr)
        return 3

    if llm_opts:
        prepared = pipeline.prepare(picks, job, llm_opts)
    files = pipeline.synthesize(prepared, backend, job)
    out = Path(args.output) if args.output else src.with_suffix(".m4b")
    seconds = assemble.build_m4b(files, [p.title for p in prepared], out, book.title, book.author,
                                 book.cover, book.cover_ext, work=job.m4b)
    print(f"\nWrote {out} ({estimate.hm(seconds / 60)}, {len(prepared)} chapters)")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a redirected Windows console can't print every title character
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = parser().parse_args(argv)
    try:
        return run(args)
    except B2AError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted. Run the same command again to resume; finished chunks are kept.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
