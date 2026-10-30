"""PDF ingestion. alice-excerpt.pdf is built by make_pdf_fixture.py from Project Gutenberg #11
(public domain) with headers, page numbers, a footnote, hyphenated line ends and bookmarks."""
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets up sys.path)
from helpers import FIXTURES, HERE

from pypdf import PdfReader, PdfWriter
from pdfminer.high_level import extract_text

from book2audio import pdf
from book2audio.book import B2AError

sys_path_fix = __import__("sys").path.insert(0, str(HERE))
import make_pdf_fixture  # noqa: E402

FIXTURE = FIXTURES / "alice-excerpt.pdf"
QUIET = lambda msg: None  # noqa: E731


class AliceExcerpt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = pdf.load(FIXTURE, log=QUIET)
        cls.source = make_pdf_fixture.excerpt()

    def test_the_fixture_really_has_the_mess_we_remove(self):
        raw = extract_text(str(FIXTURE))
        self.assertGreaterEqual(len(re.findall(r"[a-z]-\n[a-z]", raw)), 2, "hyphenated line ends")
        self.assertIn("LEWIS CARROLL", raw)
        self.assertIn("Footnote text", raw)

    def test_metadata_and_chapters_come_from_the_bookmarks(self):
        self.assertEqual(self.book.author, "Lewis Carroll")
        self.assertEqual([c.title for c in self.book.chapters], [h for h, _ in self.source])
        self.assertEqual([c.skip for c in self.book.chapters], [None] * 3)

    def test_text_matches_the_source_word_for_word(self):
        # Equal word lists mean: headers, page numbers, the footnote and its marker are gone,
        # hyphenated words are rejoined, and nothing else was lost or added.
        for chapter, (_, paras) in zip(self.book.chapters, self.source):
            self.assertEqual(chapter.text.split(), " ".join(paras).split(), chapter.title)

    def test_paragraphs_survive_including_one_that_crosses_a_page(self):
        for chapter, (_, paras) in zip(self.book.chapters, self.source):
            self.assertEqual(chapter.text.split("\n\n"), paras)

    def test_nothing_from_the_page_furniture_is_left(self):
        text = " ".join(c.text for c in self.book.chapters)
        for junk in ("LEWIS CARROLL", "ALICE'S ADVENTURES", "Footnote text", "CHAPTER I"):
            self.assertNotIn(junk, text)


class WithoutBookmarks(unittest.TestCase):
    def test_chapters_are_found_from_big_headings(self):
        with tempfile.TemporaryDirectory() as td:
            plain = Path(td) / "plain.pdf"
            w = PdfWriter(clone_from=PdfReader(str(FIXTURE)))
            del w._root_object["/Outlines"]
            w.write(str(plain))
            book = pdf.load(plain, log=QUIET)
        self.assertEqual([c.title for c in book.chapters], [h for h, _ in make_pdf_fixture.excerpt()])
        self.assertTrue(book.chapters[0].text.startswith("Alice was beginning"))

    def test_a_book_with_no_headings_is_cut_into_parts(self):
        paras = [pdf.Para("word " * 400, False, 0) for _ in range(150)]  # 150 x ~2000 chars
        chapters = pdf._chapters(paras, [], "My Book")
        self.assertGreater(len(chapters), 2)
        self.assertEqual(chapters[0].title, "My Book, part 1")
        self.assertEqual(sum(len(c.text.split("\n\n")) for c in chapters), 150)


class ScannedAndBroken(unittest.TestCase):
    def blank_pdf(self, td):
        path = Path(td) / "scan.pdf"
        w = PdfWriter()
        for _ in range(3):
            w.add_blank_page(612, 792)  # no text layer, like a page that is only a picture
        w.write(str(path))
        return path

    def test_scanned_pdf_without_ocrmypdf_says_what_to_do(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(pdf.shutil, "which", return_value=None):
            with self.assertRaises(B2AError) as cm:
                pdf.load(self.blank_pdf(td), log=QUIET)
        self.assertIn("scanned", str(cm.exception))
        self.assertIn("ocrmypdf", str(cm.exception))

    def test_scanned_pdf_is_read_from_the_ocr_result(self):
        def fake_ocrmypdf(cmd, **kw):  # stands in for ocrmypdf: output = a PDF that has text
            shutil.copy(FIXTURE, cmd[-1])
            return mock.Mock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(pdf.shutil, "which", return_value="ocrmypdf"), \
                    mock.patch.object(pdf.subprocess, "run", side_effect=fake_ocrmypdf) as run:
                book = pdf.load(self.blank_pdf(td), work_dir=Path(td) / "job", log=QUIET)
        self.assertEqual(len(book.chapters), 3)
        self.assertEqual(run.call_count, 1)

    def test_ocr_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(pdf.shutil, "which", return_value="ocrmypdf"), \
                mock.patch.object(pdf.subprocess, "run", return_value=mock.Mock(returncode=2, stderr="no tesseract")):
            with self.assertRaises(B2AError) as cm:
                pdf.load(self.blank_pdf(td), work_dir=Path(td) / "job", log=QUIET)
        self.assertIn("no tesseract", str(cm.exception))

    def test_not_a_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "x.pdf"
            bad.write_text("nope")
            with self.assertRaises(B2AError):
                pdf.load(bad, log=QUIET)


if __name__ == "__main__":
    unittest.main()
