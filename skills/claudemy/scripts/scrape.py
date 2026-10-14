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
- "substack": "name.substack.com"  -> the public archive API (all free posts).
- "site": {"kind": "sitemap", "sitemaps": [...], "url_pattern": "regex",
           "limit": 150, "min_words": 150}
      -> an own-site blog. Newest first by sitemap lastmod, body from <article>
         (or <main>), short posts skipped, stops at limit. Daily writers publish
         thousands of posts, so limit is the recency cap.
- "site": {"kind": "rss", "feed": "https://.../feed", "limit": 100, "min_words": 150}
      -> any RSS/Atom feed. Uses the feed's full content when present, else
         fetches the page.

Usage: python3 scrape.py <workspace> [name-substring | web]
Re-runs skip posts already on disk, so an interrupted run resumes.
"""
import html, json, re, sys, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("missing dependency: pip install beautifulsoup4")

UA = {"User-Agent": "Mozilla/5.0 (claudemy skill)"}
NETWORK_ERRORS = (urllib.error.URLError, ConnectionError, TimeoutError)


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def get_json(url, tries=5):
    # Substack answers 429 after ~10 fast requests; back off instead of dying.
    for i in range(tries):
        try:
            return json.loads(fetch(url))
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(15 * (i + 1))


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


def urls_on_disk(out):
    return {line[5:].strip() for f in out.glob("*.md")
            for line in f.read_text().splitlines()[:12] if line.startswith("url: ")}


def write_post(out, person, title, date, url, body, paywalled=False):
    slug = slugify(url.rstrip("/").rsplit("/", 1)[-1])[:80] or "post"
    if person["name"] == "web":
        # Web pages come from many sites, and "index" or "guide" repeats across them.
        slug = slugify(url.split("/")[2].removeprefix("www."))[:40] + "-" + slug
    (out / f"{date}-{slug}.md").write_text(
        f"---\nauthor: {person['name']}\ntitle: {json.dumps(title)}\ndate: {date}\n"
        f"url: {url}\npaywalled: {str(paywalled).lower()}\nwords: {len(body.split())}\n---\n\n{body}\n"
    )


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


def scrape_substack(ws, person, host):
    out, offset, posts = out_dir(ws, person), 0, []
    while True:
        page = get_json(f"https://{host}/api/v1/archive?sort=new&offset={offset}&limit=50")
        if not page:
            break
        posts += page
        offset += len(page)
    have, new = urls_on_disk(out), 0
    for p in posts:
        if p.get("canonical_url") in have:
            continue
        full = get_json(f"https://{host}/api/v1/posts/{p['slug']}")
        body = to_text(full.get("body_html"))
        write_post(out, person, full.get("title"), p["post_date"][:10], full.get("canonical_url"),
                   body, paywalled=full.get("audience") != "everyone")
        new += 1
        time.sleep(3)
    print(f"{person['name']}: {len(posts)} in archive, {new} new")


def sitemap_entries(site):
    """(lastmod, url) for every post URL matching the pattern, newest first."""
    pattern, entries = re.compile(site["url_pattern"]), []
    for sm in site["sitemaps"]:
        for block in re.findall(r"<url>(.*?)</url>", fetch(sm), re.S):
            loc = re.search(r"<loc>([^<]+)", block).group(1).strip()
            mod = re.search(r"<lastmod>([^<]+)", block)
            if pattern.search(loc):
                entries.append((mod.group(1)[:10] if mod else "", loc))
    return sorted(entries, reverse=True)


def save_page(out, person, url, fallback_date, min_words):
    """Fetch one page and write it if it carries enough words. True if written."""
    try:
        soup = BeautifulSoup(fetch(url), "html.parser")
    except NETWORK_ERRORS as e:
        # A dropped connection costs one post, not the run; the next run retries it.
        print(f"skipped {url}: {e}", file=sys.stderr)
        time.sleep(10)
        return False
    body = page_body(soup)
    if len(body.split()) < min_words:
        return False
    meta = soup.find("meta", property="article:published_time")
    h1 = soup.find("h1")
    date = (meta["content"] if meta else fallback_date or "undated")[:10]
    write_post(out, person, h1.get_text(strip=True) if h1 else url, date, url, body)
    return True


def scrape_sitemap(ws, person, site):
    out = out_dir(ws, person)
    have = urls_on_disk(out)
    kept = len(have)
    for lastmod, url in sitemap_entries(site):
        if kept >= site.get("limit", 150):
            break
        if url in have:
            continue
        kept += save_page(out, person, url, lastmod, site.get("min_words", 150))
        time.sleep(1)
    print(f"{person['name']}: {kept} posts on disk")


NS = {"content": "http://purl.org/rss/1.0/modules/content/", "atom": "http://www.w3.org/2005/Atom",
      "dc": "http://purl.org/dc/elements/1.1/"}


def feed_items(xml):
    """RSS 2.0 items and Atom entries. Stdlib XML parser on purpose: an HTML
    parser treats <link> as an empty tag and silently loses every item's url."""
    root = ET.fromstring(xml.encode("utf-8"))
    for item in root.iter("item"):
        yield {"url": (item.findtext("link") or "").strip(), "title": item.findtext("title") or "",
               "date": item.findtext("pubDate") or item.findtext("dc:date", namespaces=NS) or "",
               "html": item.findtext("content:encoded", namespaces=NS) or item.findtext("description") or ""}
    for entry in root.iter(f"{{{NS['atom']}}}entry"):
        link = entry.find("atom:link", NS)
        yield {"url": (link.get("href") if link is not None else "").strip(),
               "title": entry.findtext("atom:title", namespaces=NS) or "",
               "date": entry.findtext("atom:published", namespaces=NS) or entry.findtext("atom:updated", namespaces=NS) or "",
               "html": entry.findtext("atom:content", namespaces=NS) or entry.findtext("atom:summary", namespaces=NS) or ""}


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
    out = out_dir(ws, person)
    have, kept = urls_on_disk(out), 0
    min_words = site.get("min_words", 150)
    for it in feed_items(fetch(site["feed"])):
        if kept >= site.get("limit", 100) or not it["url"] or it["url"] in have:
            continue
        body = to_text(it["html"])
        if len(body.split()) >= min_words:
            write_post(out, person, it["title"], iso_date(it["date"]), it["url"], body)
            kept += 1
        else:
            kept += save_page(out, person, it["url"], iso_date(it["date"]), min_words)
            time.sleep(1)
    print(f"{person['name']}: {kept} new from feed")


def scrape_pages(ws, urls, min_words=150):
    out = ws / "raw" / "web"
    out.mkdir(parents=True, exist_ok=True)
    have, kept, thin = urls_on_disk(out), 0, []
    for url in urls:
        if url in have:
            continue
        if save_page(out, {"name": "web"}, url, "", min_words):
            kept += 1
        else:
            thin.append(url)
        time.sleep(1)
    print(f"web: {kept} new pages, {len(have)} already on disk")
    for url in thin:
        print(f"web: not saved (thin, JS-only or unreachable): {url}")


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
        except (*NETWORK_ERRORS, ET.ParseError) as e:
            # One unreachable author must not stop the others; the report names it.
            print(f"{person['name']}: FAILED, {e}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]).expanduser().resolve(), sys.argv[2].lower() if len(sys.argv) > 2 else "")
