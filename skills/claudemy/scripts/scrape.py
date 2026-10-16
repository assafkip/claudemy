"""Save what the class is built from into <workspace>/raw/, one markdown file per page.

Front matter first (author, title, date, url, paywalled, words), so every lesson
can cite a page that is really on disk and the checker can refuse one that isn't.

Two kinds of entry in <workspace>/sources.json:
- "pages": ["https://...", ...]  -> the web research reading list (the default
      mode). Each page is fetched once into raw/web/. Pages under min_words are
      skipped and named, since a thin page can't support a lesson.
- "authors": [...]  -> only when the learner asked for a specific person's work.
      One entry per person, with one of the kinds below.

Author kinds, picked by the keys on each entry:
- "substack": "name.substack.com", optional "limit": 150, "min_words": 150 on the
      author entry  -> the public archive API, newest first. Paywalled teasers
      and short posts are skipped and named.
- "site": {"kind": "sitemap", "sitemaps": [...], "url_pattern": "regex",
           "limit": 150, "min_words": 150}
      -> an own-site blog. Newest first by sitemap lastmod, body from <article>
         (or <main>), short posts skipped, stops at limit. A sitemap index is
         followed into its child sitemaps. Daily writers publish thousands of
         posts, so limit is the recency cap.
- "site": {"kind": "rss", "feed": "https://.../feed", "limit": 100, "min_words": 150}
      -> any RSS/Atom feed. Uses the feed's full content when present, else
         fetches the page.

In every mode, limit counts posts on disk for that person, so a re-run tops up
to the limit rather than adding another batch. Every page not saved is named
with the reason.

Usage: python3 scrape.py <workspace> [name-substring | web]
Re-runs skip posts already on disk, so an interrupted run resumes.
"""
import copy, hashlib, html, json, re, sys, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("missing dependency: pip install beautifulsoup4")

UA = {"User-Agent": "Mozilla/5.0 (claudemy skill)"}
NETWORK_ERRORS = (urllib.error.URLError, ConnectionError, TimeoutError)


class NotJson(ValueError):
    """An API url answered with something else, usually a bot check or login page."""


def fetch_bytes(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def fetch(url):
    # Everything is read as UTF-8, a bad byte becoming one replacement mark. Pages and
    # feeds in other encodings lose their accented and non-Latin letters: known gap,
    # GitHub issue #6, because two attempts at detection each broke other pages.
    return fetch_bytes(url).decode("utf-8", "replace")


def get_json(url, tries=5):
    # Substack answers 429 after ~10 fast requests; back off instead of dying.
    for i in range(tries):
        try:
            text = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(15 * (i + 1))
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # A Cloudflare check or login wall answers 200 with HTML; that used to
            # escape as a JSONDecodeError and stop every author after this one.
            raise NotJson(f"{url} answered with a page, not JSON (bot check or login wall?): "
                          f"{text[:80]!r}") from None


def to_text(body_html):
    t = re.sub(r"<(br|/p|/h\d|/li|/blockquote)[^>]*>", "\n", body_html or "")
    t = re.sub(r"<li[^>]*>", "- ", t)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(t)).strip()


def slugify(text):
    return re.sub(r"\W+", "-", text.lower()).strip("-")


def out_dir(ws, person):
    out = ws / "raw" / slugify(person["name"])
    out.mkdir(parents=True, exist_ok=True)
    return out


def front_url(path):
    # Posts are written as UTF-8, but files from older versions on a Windows locale, or
    # dropped in by hand, may not be; one such file used to stop the whole run.
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
        if line.startswith("url: "):
            return line[5:].strip()
    return None


def urls_on_disk(out):
    return {u for f in out.glob("*.md") if (u := front_url(f))}


def write_post(out, person, title, date, url, body, paywalled=False):
    slug = slugify(url.rstrip("/").rsplit("/", 1)[-1])[:80] or "post"
    if person["name"] == "web":
        # Web pages come from many sites, and "index" or "guide" repeats across them.
        slug = slugify(url.split("/")[2].removeprefix("www."))[:40] + "-" + slug
    path = out / f"{date}-{slug}.md"
    if path.exists() and front_url(path) != url:
        # /guide/intro and /tutorial/intro share a slug; the second used to
        # overwrite the first, and its citations then failed as "not in raw/".
        path = out / f"{date}-{slug}-{hashlib.sha1(url.encode()).hexdigest()[:6]}.md"
    path.write_text(
        f"---\nauthor: {person['name']}\ntitle: {json.dumps(title)}\ndate: {date}\n"
        f"url: {url}\npaywalled: {str(paywalled).lower()}\nwords: {len(body.split())}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def print_reasons(name, reasons):
    for url, why in reasons.items():
        print(f"{name}: not saved, {why}: {url}")


def words_in(node):
    return len(node.get_text(" ", strip=True).split()) if node else 0


def page_body(soup):
    # The first <article> is often a comment, a related-post card or a recipe box
    # (theperfectloaf.com has 42 of them, the biggest 150 words, inside a 7,700-word
    # <main>). Take the largest article, unless <main> holds twice as much.
    article = max(soup.select("article"), key=words_in, default=None)
    main = soup.select_one("main")
    node = article if words_in(article) * 2 >= words_in(main) else main
    if node is None and soup.body is not None:
        # Plenty of guides and docs pages have neither tag; take the body minus chrome.
        for junk in soup.body.select("script, style, nav, header, footer, aside, form"):
            junk.decompose()
        node = soup.body
    return node.get_text("\n", strip=True) if node else ""


def substack_archive(host):
    """Archive entries newest first, one API page at a time, so a limit stops the paging too."""
    offset = 0
    while True:
        page = get_json(f"https://{host}/api/v1/archive?sort=new&offset={offset}&limit=50")
        if not page:
            return
        yield from page
        offset += len(page)


SKIPPED = ".skipped.json"  # url -> words, for posts too short to keep; not a *.md, so never a source


def scrape_substack(ws, person, host):
    # limit and min_words used to be ignored here: a 2,000-post archive was paged in
    # full (about 100 minutes at 3 s a post) and 20-word open threads became sources.
    out = out_dir(ws, person)
    have = urls_on_disk(out)
    # Skipped posts are remembered, so a resume doesn't fetch every paywalled teaser
    # again (40 teasers cost 40 fetches and 2 minutes per re-run). A lower min_words
    # on a later run fetches them again.
    ledger_path = out / SKIPPED
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ledger = {}
    kept, new, reasons, known_short = len(have), 0, {}, 0
    limit, min_words = person.get("limit", 150), person.get("min_words", 150)
    archive = substack_archive(host)
    # The limit is checked before the next archive entry is asked for, so a run that
    # is already at the limit, or reaches it on a page's last post, fetches no more pages.
    while kept < limit:
        p = next(archive, None)
        if p is None:
            break
        key = p.get("canonical_url") or p.get("slug")
        if key in have:
            continue
        if ledger.get(key, min_words) < min_words:
            known_short += 1
            continue
        full = get_json(f"https://{host}/api/v1/posts/{p['slug']}")
        url = full.get("canonical_url") or p.get("canonical_url")
        body = to_text(full.get("body_html"))
        paywalled = full.get("audience") != "everyone"
        words = len(body.split())
        if words < min_words:
            reasons[url] = f"{'paywalled teaser' if paywalled else 'too short'} ({words} words)"
            ledger[key] = words
            ledger_path.write_text(json.dumps(ledger, indent=0), encoding="utf-8")
        else:
            write_post(out, person, full.get("title"), p["post_date"][:10], url, body, paywalled=paywalled)
            kept += 1
            new += 1
        time.sleep(3)
    print(f"{person['name']}: {kept} posts on disk, {new} new"
          + (f", {known_short} skipped on an earlier run (short or paywalled), not fetched again" if known_short else ""))
    print_reasons(person["name"], reasons)


SITEMAP_DEPTH = 2  # index -> child sitemaps -> at most one more index level


def sitemap_locs(sm, depth=0):
    """(lastmod, url) for every <url> in one sitemap. WordPress, Yoast and most
    big blogs serve a sitemap index at /sitemap.xml: <sitemap><loc> children
    instead of <url> blocks. Those are followed, SITEMAP_DEPTH levels deep;
    before this, an index read as zero posts with no message."""
    raw = fetch(sm)
    if "<sitemapindex" in raw:
        children = [m.group(1).strip() for block in re.findall(r"<sitemap>(.*?)</sitemap>", raw, re.S)
                    if (m := re.search(r"<loc>([^<]+)", block))]
        if depth >= SITEMAP_DEPTH:
            print(f"{sm}: sitemap index nested {depth + 1} deep, not followed ({len(children)} children)",
                  file=sys.stderr)
            return
        print(f"{sm}: sitemap index, following {len(children)} child sitemaps")
        for child in children:
            if child != sm:
                yield from sitemap_locs(child, depth + 1)
        return
    for block in re.findall(r"<url>(.*?)</url>", raw, re.S):
        loc = re.search(r"<loc>([^<]+)", block)
        if loc is None:
            continue
        mod = re.search(r"<lastmod>([^<]+)", block)
        yield (mod.group(1)[:10] if mod else "", loc.group(1).strip())


def sitemap_entries(site):
    """(lastmod, url) for every post URL matching the pattern, newest first."""
    pattern, newest, seen = re.compile(site["url_pattern"]), {}, 0
    for sm in site["sitemaps"]:
        for mod, loc in sitemap_locs(sm):
            seen += 1
            # One entry per url: WordPress lists each post again in its image sitemap,
            # and a repeat was fetched twice and counted twice against the limit.
            if pattern.search(loc) and mod >= newest.get(loc, ""):
                newest[loc] = mod
    if not newest:
        # Zero posts used to end the run in silence; the agent needs a reason it can act on.
        print(f"no urls matched {site['url_pattern']!r} in {len(site['sitemaps'])} sitemap(s), {seen} urls read",
              file=sys.stderr)
    return sorted(((mod, loc) for loc, mod in newest.items()), reverse=True)


PAYWALL = re.compile(r'"isAccessibleForFree"\s*:\s*"?false|subscribe to (continue|read)|to continue reading|'
                     r'already a subscriber|sign in to (read|continue)|unlock this article|for subscribers only', re.I)


def save_page(out, person, url, fallback_date, min_words, reasons=None):
    """Fetch one page and write it if it carries enough words. True if written.
    When reasons is a dict, a page that is not written gets its reason there."""
    def skip(why):
        if reasons is not None:
            reasons[url] = why
        return False
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as e:
        # A 404 here usually means a search tool invented the url; say so, don't call it thin.
        return skip(f"HTTP {e.code}, the url is wrong or the site refuses scripts")
    except NETWORK_ERRORS as e:
        # A dropped connection costs one post, not the run; the next run retries it.
        print(f"skipped {url}: {e}", file=sys.stderr)
        time.sleep(10)
        return skip(f"unreachable ({e})")
    soup = BeautifulSoup(raw, "html.parser")
    body = page_body(soup)
    words = len(body.split())
    # A paywall teaser clears a word floor on share buttons alone (HBR teasers ran 179 to 274).
    if words < 600 and PAYWALL.search(raw):
        return skip(f"paywalled teaser ({words} words)")
    if words < min_words:
        return skip(f"thin or JavaScript-only ({words} words)")
    meta = soup.find("meta", property="article:published_time")
    h1 = soup.find("h1")
    date = (meta["content"] if meta else fallback_date or "undated")[:10]
    write_post(out, person, h1.get_text(strip=True) if h1 else url, date, url, body)
    return True


def scrape_sitemap(ws, person, site):
    out = out_dir(ws, person)
    have = urls_on_disk(out)
    kept, reasons = len(have), {}
    for lastmod, url in sitemap_entries(site):
        if kept >= site.get("limit", 150):
            break
        if url in have:
            continue
        kept += save_page(out, person, url, lastmod, site.get("min_words", 150), reasons)
        time.sleep(1)
    print(f"{person['name']}: {kept} posts on disk")
    print_reasons(person["name"], reasons)


NS = {"content": "http://purl.org/rss/1.0/modules/content/", "atom": "http://www.w3.org/2005/Atom",
      "dc": "http://purl.org/dc/elements/1.1/"}


def atom_html(entry):
    """The entry's content, else its summary. type="xhtml" carries the post as child
    elements with no text of their own, which read as empty and cost a page fetch."""
    for tag in ("atom:content", "atom:summary"):
        el = entry.find(tag, NS)
        if el is None:
            continue
        if el.get("type") == "xhtml":
            parts = []
            for child in el:
                child = copy.deepcopy(child)
                for node in child.iter():
                    if isinstance(node.tag, str) and "}" in node.tag:
                        node.tag = node.tag.split("}", 1)[1]
                parts.append(ET.tostring(child, encoding="unicode"))
            content = "".join(parts)
        else:
            content = el.text or ""
        if content.strip():
            return content
    return ""


def feed_items(xml):
    """RSS 2.0 items and Atom entries. Stdlib XML parser on purpose: an HTML
    parser treats <link> as an empty tag and silently loses every item's url."""
    root = ET.fromstring(xml.encode("utf-8"))
    for item in root.iter("item"):
        yield {"url": (item.findtext("link") or "").strip(), "title": item.findtext("title") or "",
               "date": item.findtext("pubDate") or item.findtext("dc:date", namespaces=NS) or "",
               "html": item.findtext("content:encoded", namespaces=NS) or item.findtext("description") or ""}
    for entry in root.iter(f"{{{NS['atom']}}}entry"):
        # RFC 4287: rel="alternate" (or no rel) is the post's web page. Blogger lists
        # replies/edit/self links first, podcast feeds list the enclosure first.
        links = entry.findall("atom:link", NS)
        link = next((l for l in links if l.get("rel") in (None, "alternate")), links[0] if links else None)
        yield {"url": (link.get("href") if link is not None else "").strip(),
               "title": entry.findtext("atom:title", namespaces=NS) or "",
               "date": entry.findtext("atom:published", namespaces=NS) or entry.findtext("atom:updated", namespaces=NS) or "",
               "html": atom_html(entry)}


def iso_date(raw):
    m = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    if m:
        return m.group(0)
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        return "undated"


def scrape_rss(ws, person, site):
    # limit counts posts on disk, as in sitemap mode; it used to count new posts per run.
    out = out_dir(ws, person)
    have = urls_on_disk(out)
    kept, new, reasons = len(have), 0, {}
    limit, min_words = site.get("limit", 100), site.get("min_words", 150)
    for it in feed_items(fetch(site["feed"])):
        if kept >= limit:
            break
        if not it["url"] or it["url"] in have:
            continue
        body = to_text(it["html"])
        if len(body.split()) >= min_words:
            write_post(out, person, it["title"], iso_date(it["date"]), it["url"], body)
            saved = True
        else:
            saved = save_page(out, person, it["url"], iso_date(it["date"]), min_words, reasons)
            time.sleep(1)
        kept += saved
        new += saved
    print(f"{person['name']}: {kept} posts on disk, {new} new from feed")
    print_reasons(person["name"], reasons)


def scrape_pages(ws, urls, min_words=150):
    out = ws / "raw" / "web"
    out.mkdir(parents=True, exist_ok=True)
    have, kept, reasons = urls_on_disk(out), 0, {}
    for url in urls:
        if url in have:
            continue
        kept += save_page(out, {"name": "web"}, url, "", min_words, reasons)
        time.sleep(1)
    print(f"web: {kept} new pages saved, {len(have)} already on disk, {kept + len(have)} in total")
    print_reasons("web", reasons)


def main(ws, want=""):
    cfg = json.loads((ws / "sources.json").read_text())
    if cfg.get("pages") and want in ("", "web"):
        scrape_pages(ws, cfg["pages"], cfg.get("min_words", 150))
    for person in cfg.get("authors", []):
        if want not in person["name"].lower():
            continue
        site = person.get("site") or {}
        try:
            if person.get("substack"):
                scrape_substack(ws, person, person["substack"])
            if site.get("kind") == "sitemap":
                scrape_sitemap(ws, person, site)
            elif site.get("kind") == "rss":
                scrape_rss(ws, person, site)
        except (*NETWORK_ERRORS, ET.ParseError, NotJson) as e:
            # One unreachable author must not stop the others; the report names it.
            print(f"{person['name']}: FAILED, {e}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]).expanduser().resolve(), sys.argv[2].lower() if len(sys.argv) > 2 else "")
