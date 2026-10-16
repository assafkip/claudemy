"""Check every lesson in <workspace>/class/ before its audio is rendered.

A lesson passes when its script is two-host dialogue of about 2 minutes with
no banned language, and its card has the standard sections and cites only
pages that are actually on disk in <workspace>/raw/. A citation to a page the
class never read is how invented sources get in, so it is a hard fail.

Usage: python3 check_lessons.py <workspace> [lesson-folder ...]   (default: all)
Exit 1 if any lesson fails.
"""
import re, sys
from pathlib import Path

CARD_SECTIONS = ["**Listen:**", "The idea, in three lines", "**Impact:**", "**Who says it:**",
                 "**Try it**", "**Rule to keep**", "**Skip**",
                 "**Go deeper (optional)**"]
# Demand words land as pressure on many learners (and on PDA profiles as a shutdown trigger).
DEMAND = re.compile(r"\b(you need to|you must|you should|make sure|you have to|don't forget)\b", re.I)
DASH = re.compile(r"—|–|(?<!<!)--(?!>)")
TAG = re.compile(r"\[[a-z ]+\]")
# 280 to 350 words renders at about 2:00 to 2:30. Measured: 347 words ran 2:27, 371 ran 2:32.
WORDS_MIN, WORDS_MAX, TAGS_MAX = 280, 350, 3


# Balanced parentheses stay in the url (Wikipedia's Mercury_(planet)); a lone ")" ends
# it, as in a markdown link. Backticks, brackets and angle brackets wrap urls, never end them.
URL = re.compile(r"https?://(?:[^\s()<>\[\]`]|\([^\s()<>]*\))+")
# Bold, code spans and sentence ends trail urls in markdown; none of that is part of the url.
TRAILING = ".,;:!?*_'\"`"


def cited_urls(text):
    return [u.rstrip(TRAILING) for u in URL.findall(text)]


def same_page(url):
    """One key per page: scheme, www., #fragment and a trailing slash don't change
    the page. Exact matching failed valid citations and sent the writer round the
    fix loop up to three times for nothing. Trailing marks come off both sides,
    so a url that really ends in "_" or "!" still matches itself."""
    url = url.rstrip(TRAILING)
    m = re.match(r"https?://([^/?#]+)([^#]*)", url, re.I)
    if not m:
        return url
    path, q, query = m.group(2).partition("?")
    return m.group(1).lower().removeprefix("www.") + path.rstrip("/") + q + query


def scraped_urls(ws):
    # scrape.py writes UTF-8; reading in the locale's encoding crashed on Windows-style locales.
    return {line[5:].strip() for f in ws.glob("raw/*/*.md")
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines()[:12] if line.startswith("url: ")}


def banned(text):
    found = []
    if DASH.search(text):
        found.append("emdash or double hyphen")
    m = DEMAND.search(text)
    if m:
        found.append(f"demand phrase {m.group(0)!r}")
    return found


def check_script(text):
    lines = [l for l in text.splitlines() if l.strip()]
    bad = [l for l in lines if not re.match(r"^[AB]: \S", l)]
    words = len(re.sub(r"^[AB]:", "", text, flags=re.M).split())
    problems = [f"{len(bad)} lines not 'A:'/'B:' (first: {bad[0][:40]!r})"] if bad else []
    if not WORDS_MIN <= words <= WORDS_MAX:
        problems.append(f"{words} words, want {WORDS_MIN} to {WORDS_MAX} (about 2 minutes)")
    if len(TAG.findall(text)) > TAGS_MAX:
        problems.append(f"{len(TAG.findall(text))} audio tags, max {TAGS_MAX}")
    return problems + [f"script: {m}" for m in banned(text)], words


def check_card(text, urls):
    # Every check runs on what the learner sees. HTML comments (editor notes, a
    # commented-out draft section) are not content: a section that exists only
    # inside one is missing, a demand phrase inside one is not a fail.
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    problems = [f"card missing {s!r}" for s in CARD_SECTIONS if s not in body]
    problems += [f"card: {m}" for m in banned(body)]
    cited = cited_urls(body)
    if not cited:
        problems.append("card cites no source")
    known = {same_page(u) for u in urls}
    problems += [f"card cites a page that is not in raw/: {u}" for u in cited if same_page(u) not in known]
    return problems


def check_plan(ws, urls):
    """The plan cites pages too. In the first full test, checking it by hand caught
    3 stories credited to the wrong page; a url not on disk is the part a script can catch."""
    plan = ws / "class" / "lesson-plan.md"
    if not plan.exists():
        return 0
    cited = set(cited_urls(plan.read_text(encoding="utf-8")))
    if not cited:
        # A plan that names sources without links has nothing this check can test; "ok" read as a pass.
        print("skip lesson-plan.md (cites no urls, nothing to check)")
        return 0
    known = {same_page(u) for u in urls}
    missing = sorted(u for u in cited if same_page(u) not in known)
    print(f"{'FAIL' if missing else 'ok  '} lesson-plan.md ({len(cited)} urls)")
    for u in missing:
        print(f"     plan cites a page that is not in raw/: {u}")
    return bool(missing)


def main(ws, folders):
    # A url or name the console can't show must not crash the report.
    sys.stdout.reconfigure(errors="replace")
    urls = scraped_urls(ws)
    failed = check_plan(ws, urls)
    for d in folders:
        script, card = d / "script.txt", d / "card.md"
        if not (script.exists() and card.exists()):
            print(f"FAIL {d.name}: missing script.txt or card.md")
            failed += 1
            continue
        problems, words = check_script(script.read_text(encoding="utf-8"))
        problems += check_card(card.read_text(encoding="utf-8"), urls)
        print(f"{'FAIL' if problems else 'ok  '} {d.name} ({words} words)")
        for p in problems:
            print(f"     {p}")
        failed += bool(problems)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ws = Path(sys.argv[1]).expanduser().resolve()
    folders = [Path(a) for a in sys.argv[2:]] or sorted(p for p in (ws / "class").glob("[0-9][0-9]-*") if p.is_dir())
    main(ws, folders)
