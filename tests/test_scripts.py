"""Regression tests for skills/claudemy/scripts. Stdlib only.

Run from the repo root:  python3 -m unittest discover -s tests
Each test names the GitHub issue it guards.
"""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "claudemy" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_lessons  # noqa: E402
import package_class  # noqa: E402
import scrape  # noqa: E402


ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <title>Blogger order</title>
  <published>2024-01-02T00:00:00Z</published>
  <content type="html">short summary</content>
  <link rel="replies" type="application/atom+xml" href="https://blog.example.com/feeds/123/comments/default"/>
  <link rel="edit" type="application/atom+xml" href="https://www.blogger.com/feeds/1/posts/default/123"/>
  <link rel="self" type="application/atom+xml" href="https://www.blogger.com/feeds/1/posts/default/123"/>
  <link rel="alternate" type="text/html" href="https://blog.example.com/2024/01/my-post.html"/>
</entry>
<entry>
  <title>No rel at all</title>
  <link href="https://blog.example.com/2024/01/plain.html"/>
</entry>
<entry>
  <title>Enclosure first</title>
  <link rel="enclosure" type="audio/mpeg" href="https://blog.example.com/ep1.mp3"/>
  <link rel="alternate" type="text/html" href="https://blog.example.com/2024/01/ep1.html"/>
</entry>
<entry>
  <title>Only a self link</title>
  <link rel="self" href="https://blog.example.com/feeds/999"/>
</entry>
</feed>"""


class AtomLinks(unittest.TestCase):
    """Issue #2: the entry url is the rel="alternate" link, not the first <link>."""

    def test_prefers_alternate_over_earlier_links(self):
        urls = [it["url"] for it in scrape.feed_items(ATOM)]
        self.assertEqual(urls[0], "https://blog.example.com/2024/01/my-post.html")
        self.assertEqual(urls[1], "https://blog.example.com/2024/01/plain.html")
        self.assertEqual(urls[2], "https://blog.example.com/2024/01/ep1.html")

    def test_falls_back_to_the_only_link(self):
        urls = [it["url"] for it in scrape.feed_items(ATOM)]
        self.assertEqual(urls[3], "https://blog.example.com/feeds/999")


INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://site.com/post-sitemap1.xml</loc><lastmod>2024-05-01</lastmod></sitemap>
<sitemap><loc>https://site.com/post-sitemap2.xml</loc><lastmod>2024-06-01</lastmod></sitemap>
<sitemap><loc>https://site.com/page-sitemap.xml</loc></sitemap>
</sitemapindex>"""

CHILD = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://site.com/blog/{a}</loc><lastmod>{da}T10:00:00+00:00</lastmod></url>
<url><loc>https://site.com/blog/{b}</loc><lastmod>{db}</lastmod></url>
<url><loc>https://site.com/about</loc></url>
</urlset>"""

SELF_INDEX = """<sitemapindex><sitemap><loc>https://loop.com/sitemap.xml</loc></sitemap></sitemapindex>"""


class SitemapIndex(unittest.TestCase):
    """Issue #3: a sitemap index is followed instead of yielding zero posts."""

    def test_follows_child_sitemaps(self):
        pages = {
            "https://site.com/sitemap.xml": INDEX,
            "https://site.com/post-sitemap1.xml": CHILD.format(a="one", da="2024-01-05", b="two", db="2024-02-05"),
            "https://site.com/post-sitemap2.xml": CHILD.format(a="three", da="2024-03-05", b="four", db="2024-04-05"),
            "https://site.com/page-sitemap.xml": "<urlset><url><loc>https://site.com/contact</loc></url></urlset>",
        }
        site = {"sitemaps": ["https://site.com/sitemap.xml"], "url_pattern": r"site\.com/blog/"}
        with mock.patch.object(scrape, "fetch", side_effect=lambda u: pages[u]):
            entries = scrape.sitemap_entries(site)
        self.assertEqual(entries, [
            ("2024-04-05", "https://site.com/blog/four"),
            ("2024-03-05", "https://site.com/blog/three"),
            ("2024-02-05", "https://site.com/blog/two"),
            ("2024-01-05", "https://site.com/blog/one"),
        ])

    def test_plain_urlset_still_works(self):
        pages = {"https://site.com/post-sitemap1.xml": CHILD.format(a="x", da="2024-01-01", b="y", db="2024-01-02")}
        site = {"sitemaps": ["https://site.com/post-sitemap1.xml"], "url_pattern": r"site\.com/blog/"}
        with mock.patch.object(scrape, "fetch", side_effect=lambda u: pages[u]):
            entries = scrape.sitemap_entries(site)
        self.assertEqual([u for _, u in entries], ["https://site.com/blog/y", "https://site.com/blog/x"])

    def test_self_referencing_index_terminates(self):
        pages = {"https://loop.com/sitemap.xml": SELF_INDEX}
        site = {"sitemaps": ["https://loop.com/sitemap.xml"], "url_pattern": r"loop\.com/"}
        with mock.patch.object(scrape, "fetch", side_effect=lambda u: pages[u]) as f:
            entries = scrape.sitemap_entries(site)
        self.assertEqual(entries, [])
        self.assertLess(f.call_count, 10)


CARD_OK = """**Listen:** x.mp3 (2 min)
**The idea, in three lines**
**Impact:** things
**Who says it:** people
**Try it** · Quick Win · 5 min
**Rule to keep** rule
**Skip** none
**Go deeper (optional)** links
https://example.com/a"""

CARD_TRY_IT_COMMENTED = """<!-- draft: **Try it** placeholder to fill in after render -->
**Listen:** x.mp3 (2 min)
**The idea, in three lines**
**Impact:** things
**Who says it:** people
**Rule to keep** rule
**Skip** none
**Go deeper (optional)** links
https://example.com/a"""

CARD_DEMAND_IN_COMMENT = CARD_OK.replace("**Try it**", "<!-- editor note: you must fix the ending -->\n**Try it**")

CARD_URL_ONLY_IN_COMMENT = CARD_OK.replace("\nhttps://example.com/a", "\n<!-- https://example.com/a -->")

CARD_BAD_URL_IN_COMMENT = CARD_OK + "\n<!-- maybe also https://example.com/never-fetched -->"


class CardComments(unittest.TestCase):
    """Issue #4: every card check runs on the text the learner sees, comments removed."""

    URLS = {"https://example.com/a"}

    def test_clean_card_passes(self):
        self.assertEqual(check_lessons.check_card(CARD_OK, self.URLS), [])

    def test_section_only_inside_a_comment_is_missing(self):
        problems = check_lessons.check_card(CARD_TRY_IT_COMMENTED, self.URLS)
        self.assertIn("card missing '**Try it**'", problems)

    def test_demand_phrase_inside_a_mid_card_comment_is_ignored(self):
        self.assertEqual(check_lessons.check_card(CARD_DEMAND_IN_COMMENT, self.URLS), [])

    def test_url_only_inside_a_comment_does_not_count_as_a_source(self):
        problems = check_lessons.check_card(CARD_URL_ONLY_IN_COMMENT, self.URLS)
        self.assertIn("card cites no source", problems)

    def test_unfetched_url_inside_a_comment_does_not_fail(self):
        self.assertEqual(check_lessons.check_card(CARD_BAD_URL_IN_COMMENT, self.URLS), [])


class ZipMembers(unittest.TestCase):
    """Issue #5: two mp3s in one lesson folder keep distinct names in the zip."""

    def test_duplicate_mp3s_keep_distinct_member_names(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            one = ws / "class" / "01-lesson"
            two = ws / "class" / "02-other"
            one.mkdir(parents=True)
            two.mkdir(parents=True)
            (one / "old.mp3").write_bytes(b"OLD AUDIO")
            (one / "new.mp3").write_bytes(b"NEW AUDIO")
            (two / "other.mp3").write_bytes(b"OTHER")
            out = ws / "deliver"
            out.mkdir()
            made = package_class.zip_audio(ws, out, 1024 * 1024)
            with zipfile.ZipFile(made[0]) as z:
                names = z.namelist()
                self.assertEqual(len(names), 3)
                self.assertEqual(len(set(names)), 3, names)
                # A folder with one mp3 keeps the numbered lesson name the learner sees today.
                self.assertIn("02-other.mp3", names)
                self.assertEqual(z.read("02-other.mp3"), b"OTHER")
                payloads = {z.read(n) for n in names}
                self.assertEqual(payloads, {b"OLD AUDIO", b"NEW AUDIO", b"OTHER"})


if __name__ == "__main__":
    unittest.main()
