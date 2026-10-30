"""EPUB ingestion. alice.epub is Project Gutenberg #11 (public domain), kept unmodified."""
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets up sys.path)
from helpers import FIXTURES, WORDS, make_epub

from book2audio import epub
from book2audio.book import B2AError


class AliceFromGutenberg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = epub.load(FIXTURES / "alice.epub")
        cls.kept = [c for c in cls.book.chapters if not c.skip]

    def test_metadata_and_cover(self):
        self.assertEqual(self.book.title, "Alice's Adventures in Wonderland")
        self.assertEqual(self.book.author, "Lewis Carroll")
        self.assertGreater(len(self.book.cover), 1000)
        self.assertEqual(self.book.cover_ext, "jpg")

    def test_twelve_chapters_from_the_toc(self):
        self.assertEqual(len(self.kept), 12)
        self.assertEqual(self.kept[0].title, "CHAPTER I. Down the Rabbit-Hole")
        self.assertEqual(self.kept[-1].title, "CHAPTER XII. Alice’s Evidence")

    def test_gutenberg_front_and_back_matter_is_skipped(self):
        skipped = {c.title: c.skip for c in self.book.chapters if c.skip}
        self.assertEqual(skipped["Contents"], "front/back matter")
        self.assertEqual(skipped["THE FULL PROJECT GUTENBERG™ LICENSE"], "front/back matter")
        self.assertEqual(len(skipped), 4)  # title, edition line, contents, licence
        self.assertNotIn("Gutenberg", " ".join(c.text for c in self.kept))

    def test_chapter_text_is_prose_without_its_own_heading(self):
        first, last = self.kept[0], self.kept[-1]
        self.assertTrue(first.text.startswith("Alice was beginning to get very tired"))
        self.assertTrue(last.text.rstrip().endswith("THE END"))
        self.assertGreater(len(first.text.split()), 2000)


class SmallBooks(unittest.TestCase):
    def load(self, pages, toc):
        with tempfile.TemporaryDirectory() as td:
            return epub.load(make_epub(Path(td) / "t.epub", pages, toc))

    def test_toc_anchors_split_one_page_into_chapters(self):
        page = (f'<h1 id="c1">One</h1><p>{WORDS}</p><p>First end.</p>'
                f'<h1 id="c2">Two</h1><p>{WORDS}</p><p>Second end.</p>')
        book = self.load({"all.xhtml": page}, [("One", "all.xhtml#c1"), ("Two", "all.xhtml#c2")])
        self.assertEqual([c.title for c in book.chapters], ["One", "Two"])
        self.assertTrue(book.chapters[0].text.endswith("First end."))
        self.assertTrue(book.chapters[1].text.endswith("Second end."))
        self.assertNotIn("Second end", book.chapters[0].text)
        self.assertEqual(book.title, "Test Book")
        self.assertEqual(book.author, "Ann Author")

    def test_footnotes_are_dropped(self):
        page = (f'<h1>One</h1><p>{WORDS} A claim<sup><a href="#n1">1</a></sup> follows.</p>'
                f'<aside epub:type="footnote" id="n1"><p>1. See page 99 of nothing.</p></aside>')
        text = self.load({"a.xhtml": page}, [("One", "a.xhtml")]).chapters[0].text
        self.assertIn("A claim follows.", text)
        self.assertNotIn("page 99", text)

    def test_non_prose_becomes_a_spoken_description(self):
        page = (f'<h1>One</h1><p>{WORDS}</p>'
                '<table><tr><th>Name</th><th>Age</th></tr><tr><td>Ann</td><td>3</td></tr>'
                '<tr><td>Bo</td><td>4</td></tr></table>'
                '<pre>x = 1\nprint(x)</pre>'
                '<figure><img src="m.png" alt="ignored"/><figcaption>A map of the island.</figcaption></figure>')
        text = self.load({"a.xhtml": page}, [("One", "a.xhtml")]).chapters[0].text
        self.assertIn("There is a table here with 3 rows and 2 columns, covering Name, Age.", text)
        self.assertIn("There is a code listing here, which is not read aloud.", text)
        self.assertIn("There is a figure here: A map of the island.", text)
        self.assertNotIn("print(x)", text)

    def test_front_matter_is_flagged_by_title_type_and_length(self):
        pages = {"cp.xhtml": f"<p>{WORDS}</p>", "pre.xhtml": ("frontmatter", f"<p>{WORDS}</p>"),
                 "ch.xhtml": f"<p>{WORDS}</p>", "dd.xhtml": "<p>For Mum.</p>"}
        book = self.load(pages, [("Copyright", "cp.xhtml"), ("Preface", "pre.xhtml"),
                                 ("Chapter 1", "ch.xhtml"), ("Epigraph", "dd.xhtml")])
        reasons = {c.title: c.skip for c in book.chapters}
        self.assertEqual(reasons["Copyright"], "front/back matter")
        self.assertEqual(reasons["Preface"], "front/back matter (epub:type frontmatter)")
        self.assertIsNone(reasons["Chapter 1"])
        self.assertEqual(reasons["Epigraph"], "too short (2 words)")

    def test_a_real_chapter_with_a_matter_like_word_is_kept(self):
        book = self.load({"a.xhtml": f"<p>{WORDS}</p>"}, [("Cover Story", "a.xhtml")])
        self.assertIsNone(book.chapters[0].skip)

    def test_not_an_epub(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "x.epub"
            bad.write_text("not a zip")
            with self.assertRaises(B2AError):
                epub.load(bad)


if __name__ == "__main__":
    unittest.main()
