"""The dry-run report: chapters, characters, and estimated time and cost per backend.

Nothing here synthesizes or sends text anywhere. Numbers are estimates:
- audio length assumes about 150 spoken words a minute (900 characters);
- synthesis speeds are rough guesses, so time a small run with --chapters 1 to calibrate;
- cost is only shown when you give the price of 1,000 ElevenLabs credits (plans differ).
"""
from . import llm
from .chunk import chunk
from .pipeline import Job, Prepared
from .tts import BACKENDS, Backend, cache_path, make_backend

CHARS_PER_AUDIO_MINUTE = 900
SYNTH_CHARS_PER_MINUTE = {"elevenlabs": 12000, "piper": 9000, "say": 15000, "google": 12000}  # rough guesses, see module doc
PRIVACY = {"elevenlabs": "ElevenLabs (cloud)", "google": "Google Cloud (cloud)", "piper": None, "say": None}


def hm(minutes: float) -> str:
    minutes = round(minutes)
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes} min"


def report(book, prepared: list[Prepared], skipped, job: Job, backend: Backend, source_name: str,
           llm_opts=None, price_per_1k=None, dry_run=True) -> str:
    total = sum(len(p.text) for p in prepared)
    lines = [("DRY RUN: nothing is synthesized or sent anywhere." if dry_run else "Estimate for this run:"), "",
             f"{book.title}" + (f" by {book.author}" if book.author else ""),
             f"{source_name}: {len(prepared)} chapters to narrate, {len(skipped)} skipped", ""]
    lines.append(f"  {'#':>3}  {'Chapter':<46}{'Characters':>11}  {'Audio':>8}")
    for p in prepared:
        title = p.title if len(p.title) <= 45 else p.title[:42] + "..."
        lines.append(f"  {p.number:>3}  {title:<46}{len(p.text):>11,}  {hm(len(p.text) / CHARS_PER_AUDIO_MINUTE):>8}")
    lines.append(f"  {'':>3}  {'Total':<46}{total:>11,}  {hm(total / CHARS_PER_AUDIO_MINUTE):>8}")
    if skipped:
        lines += ["", "Skipped (use --keep-all to narrate them anyway):"]
        lines += [f"  - {c.title[:60]!r}: {c.skip or 'no text'}" for c in skipped]

    lines += ["", f"{'Backend':<12}{'To synthesize':>16}{'Cached':>12}  {'Est. time':>10}  Cost"]
    for name in BACKENDS:
        b = backend if name == backend.name else make_backend(name)
        sizes = [(len(c), cache_path(b, c, job.tts).exists()) for p in prepared for c in chunk(p.text, b.max_chars)]
        todo = sum(n for n, hit in sizes if not hit)
        cached = sum(n for n, hit in sizes if hit)
        mark = " <- selected" if name == backend.name else ""
        if b.paid:
            credits = todo * b.credit_per_char
            cost = f"{credits:,.0f} {b.unit}" + (f" = {credits / 1000 * price_per_1k:,.2f} at {price_per_1k} per 1,000"
                                               if price_per_1k is not None else " (add --price-per-1k to see money)")
        else:
            cost = "free" + (" (macOS only)" if name == "say" else " (local)")
        lines.append(f"{name:<12}{todo:>13,} ch{cached:>9,} ch  {hm(todo / SYNTH_CHARS_PER_MINUTE.get(name, 10000)):>10}  "
                     f"{cost}{mark}")

    if llm_opts:
        e = llm.estimate(total, llm_opts["mode"], llm_opts["condense"], llm_opts["model"])
        usd = f"about ${e['usd']:.2f} at list price" if e["usd"] is not None else "no price on file for this model"
        lines += ["", f"Claude pass ({llm_opts['mode']}, {llm_opts['model']}): {e['requests']} requests, about "
                      f"{e['tokens_in']:,} tokens in and {e['tokens_out']:,} out, {usd} (excludes thinking tokens; "
                      "only this estimate is shown now, the pass runs on the real run)."]

    sent = [PRIVACY.get(backend.name)] + (["Anthropic (cloud)"] if llm_opts else [])
    sent = [s for s in sent if s]
    lines += ["", ("The text of this book will be sent to " + " and ".join(sent) + "." if sent
                   else "The text stays on this computer.")]
    return "\n".join(lines)
