"""The dry-run estimate: chapters, characters, and estimated time and cost per backend.

compute() returns plain data (the web page reads it); report() prints the same numbers for the command line.
Nothing here synthesizes or sends text anywhere. Numbers are estimates:
- audio length assumes about 150 spoken words a minute (900 characters);
- synthesis speeds are rough guesses, so time a small run with --chapters 1 to calibrate;
- cost is only shown when you give the price of 1,000 ElevenLabs credits or Google characters (plans differ).
"""
from . import llm
from .chunk import chunk
from .pipeline import Job, Prepared
from .tts import BACKENDS, Backend, cache_path, make_backend

CHARS_PER_AUDIO_MINUTE = 900
SYNTH_CHARS_PER_MINUTE = {"elevenlabs": 12000, "piper": 9000, "say": 15000, "google": 12000}  # rough guesses, see module doc
PROVIDER = {"elevenlabs": "ElevenLabs", "google": "Google Cloud"}  # who receives the text; local engines are absent


def hm(minutes: float) -> str:
    minutes = round(minutes)
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes} min"


def compute(prepared: list[Prepared], skipped, job: Job, backend: Backend, llm_opts=None, price_per_1k=None,
            every_backend=True) -> dict:
    """-> chapters, per-backend work/time/cost, the Claude pass estimate and who receives the text."""
    total = sum(len(p.text) for p in prepared)
    backends = []
    for name in (BACKENDS if every_backend else [backend.name]):
        b = backend if name == backend.name else make_backend(name)
        sizes = [(len(c), cache_path(b, c, job.tts).exists()) for p in prepared for c in chunk(p.text, b.max_chars)]
        todo = sum(n for n, hit in sizes if not hit)
        units = todo * b.credit_per_char if b.paid else 0
        backends.append({"name": name, "selected": name == backend.name, "paid": b.paid, "unit": b.unit,
                         "todo_chars": todo, "cached_chars": sum(n for n, hit in sizes if hit),
                         "minutes": todo / SYNTH_CHARS_PER_MINUTE.get(name, 10000), "units": units,
                         "money": units / 1000 * price_per_1k if b.paid and price_per_1k is not None else None})
    claude = None
    if llm_opts:
        claude = {**llm.estimate(total, llm_opts["mode"], llm_opts["condense"], llm_opts["model"]),
                  "mode": llm_opts["mode"], "model": llm_opts["model"]}
    sent_to = [n for n in [PROVIDER.get(backend.name)] if n] + (["Anthropic"] if llm_opts else [])
    return {"chapters": [{"number": p.number, "title": p.title, "chars": len(p.text),
                          "minutes": len(p.text) / CHARS_PER_AUDIO_MINUTE} for p in prepared],
            "skipped": [{"title": c.title, "reason": c.skip or "no text"} for c in skipped],
            "chars": total, "minutes": total / CHARS_PER_AUDIO_MINUTE, "price_per_1k": price_per_1k,
            "backends": backends, "claude": claude, "sent_to": sent_to}


def report(book, prepared: list[Prepared], skipped, job: Job, backend: Backend, source_name: str,
           llm_opts=None, price_per_1k=None, dry_run=True) -> str:
    est = compute(prepared, skipped, job, backend, llm_opts, price_per_1k)
    lines = [("DRY RUN: nothing is synthesized or sent anywhere." if dry_run else "Estimate for this run:"), "",
             f"{book.title}" + (f" by {book.author}" if book.author else ""),
             f"{source_name}: {len(prepared)} chapters to narrate, {len(skipped)} skipped", ""]
    lines.append(f"  {'#':>3}  {'Chapter':<46}{'Characters':>11}  {'Audio':>8}")
    for p, row in zip(prepared, est["chapters"]):
        title = p.title if len(p.title) <= 45 else p.title[:42] + "..."
        lines.append(f"  {p.number:>3}  {title:<46}{row['chars']:>11,}  {hm(row['minutes']):>8}")
    lines.append(f"  {'':>3}  {'Total':<46}{est['chars']:>11,}  {hm(est['minutes']):>8}")
    if skipped:
        lines += ["", "Skipped (use --keep-all to narrate them anyway):"]
        lines += [f"  - {s['title'][:60]!r}: {s['reason']}" for s in est["skipped"]]

    lines += ["", f"{'Backend':<12}{'To synthesize':>16}{'Cached':>12}  {'Est. time':>10}  Cost"]
    for b in est["backends"]:
        if b["paid"]:
            cost = f"{b['units']:,.0f} {b['unit']}" + (f" = {b['money']:,.2f} at {price_per_1k} per 1,000"
                                                    if b["money"] is not None else " (add --price-per-1k to see money)")
        else:
            cost = "free" + (" (macOS only)" if b["name"] == "say" else " (local)")
        lines.append(f"{b['name']:<12}{b['todo_chars']:>13,} ch{b['cached_chars']:>9,} ch  {hm(b['minutes']):>10}  "
                     f"{cost}{' <- selected' if b['selected'] else ''}")

    if est["claude"]:
        e = est["claude"]
        usd = f"about ${e['usd']:.2f} at list price" if e["usd"] is not None else "no price on file for this model"
        lines += ["", f"Claude pass ({e['mode']}, {e['model']}): {e['requests']} requests, about "
                      f"{e['tokens_in']:,} tokens in and {e['tokens_out']:,} out, {usd} (excludes thinking tokens; "
                      "only this estimate is shown now, the pass runs on the real run)."]

    sent = [f"{s} (cloud)" for s in est["sent_to"]]
    lines += ["", ("The text of this book will be sent to " + " and ".join(sent) + "." if sent
                   else "The text stays on this computer.")]
    return "\n".join(lines)
