"""Speech normalization and chunking, including a pass over a real Gutenberg chapter."""
import re
import unittest

import helpers  # noqa: F401  (sets up sys.path)
from helpers import FIXTURES

from book2audio import epub
from book2audio.chunk import chunk
from book2audio.normalize import normalize, normalize_paragraph, ordinal, words, year

CASES = [
    # abbreviations
    ("Mr. Smith met Dr. Jones.", "Mister Smith met Doctor Jones."),
    ("Apples, pears, etc. They sold it.", "Apples, pears, et cetera. They sold it."),
    ("Apples, pears, etc., and nuts.", "Apples, pears, et cetera, and nuts."),
    ("Arrive at 10 a.m. Bring lunch.", "Arrive at ten A M. Bring lunch."),
    ("The U.S. troops left.", "The U S troops left."),
    ("He left the U.S. Then he slept.", "He left the U S. Then he slept."),
    ("See Fig. 3, i.e. the map, e.g. roads.", "See Figure three, that is, the map, for example, roads."),
    ("On Oct. 5 and Sept. 12.", "On October five and September twelve."),
    # numbers
    ("In 1984, 25% of 1,200 people paid $3 million.",
     "In nineteen eighty-four, twenty-five percent of one thousand two hundred people paid three million dollars."),
    ("He earned £2,500 and €10 and $5.50 and $1.", "He earned two thousand five hundred pounds and ten euros and "
                                                     "five dollars fifty cents and one dollar."),
    ("It cost $0.99.", "It cost ninety-nine cents."),
    ("the 1st, 2nd and 21st", "the first, second and twenty-first"),
    ("Pi is 3.14.", "Pi is three point one four."),
    ("Meet at 3:30 or 3:00 or 3:05.", "Meet at three thirty or three o'clock or three oh five."),
    ("in 2024 and 2,000 words and 2500 more", "in twenty twenty-four and two thousand words and "
                                              "two thousand five hundred more"),
    ("In 2024 it rained; in 1905 too.", "In twenty twenty-four it rained; in nineteen oh five too."),
    ("It was -5 degrees.", "It was minus five degrees."),
    ("pages 10-12 and 1990-1995", "pages ten to twelve and nineteen ninety to nineteen ninety-five"),
    ("Chapter 7 and CHAPTER IV. The Rabbit", "Chapter seven and CHAPTER four. The Rabbit"),
    ("the part I played", "the part I played"),
    # urls, emails, symbols
    ("Visit https://www.example.com/page?x=1 today.", "Visit example dot com today."),
    ("Visit www.my-site.org.", "Visit my dash site dot org."),
    ("Mail john.smith@example.com now.", "Mail john dot smith at example dot com now."),
    ("Tom & Jerry: 50% off, 2+2=4.", "Tom and Jerry: fifty percent off, two plus two equals four."),
    ("his/her book, #5, 20°", "his or her book, number five, twenty degrees"),
    # punctuation and clean-up
    ("She wrote—and then stopped.", "She wrote, and then stopped."),
    ("“If you please, sir—” The Rabbit left.", "“If you please, sir” The Rabbit left."),
    ("[Illustration] Text[1] and [a] more.", "Text and more."),
    ("ﬁnal ﬂight", "final flight"),
    ("* * *", ""),
]


class Normalize(unittest.TestCase):
    def test_table(self):
        for src, want in CASES:
            with self.subTest(src):
                self.assertEqual(normalize_paragraph(src), want)

    def test_paragraph_breaks_are_kept_and_empty_ones_dropped(self):
        self.assertEqual(normalize("One.\n\n* * *\n\nTwo."), "One.\n\nTwo.")

    def test_number_words(self):
        self.assertEqual(words(0), "zero")
        self.assertEqual(words(101), "one hundred one")
        self.assertEqual(words(1_000_001), "one million one")
        self.assertEqual(ordinal(40), "fortieth")
        self.assertEqual(ordinal(112), "one hundred twelfth")
        self.assertEqual((year(1900), year(2010), year(1100)), ("nineteen hundred", "twenty ten", "eleven hundred"))

    def test_phone_like_and_zero_padded_numbers_are_read_digit_by_digit(self):
        self.assertEqual(normalize_paragraph("Agent 007"), "Agent zero zero seven")


class WithGutenbergText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        book = epub.load(FIXTURES / "alice.epub")
        cls.text = [c for c in book.chapters if not c.skip][0].text

    def test_prose_words_survive_unchanged(self):
        before = re.findall(r"[A-Za-z’']+", self.text)
        after = re.findall(r"[A-Za-z’']+", normalize(self.text))
        self.assertEqual(after, before)

    def test_dashes_become_pauses(self):
        self.assertIn("—", self.text)
        self.assertNotIn("—", normalize(self.text))


class Chunking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = normalize([c for c in epub.load(FIXTURES / "alice.epub").chapters if not c.skip][0].text)

    def test_every_chunk_fits_and_no_word_is_lost(self):
        for limit in (200, 800, 2500):
            chunks = chunk(self.text, limit)
            self.assertTrue(all(len(c) <= limit for c in chunks), limit)
            self.assertEqual(" ".join(chunks).split(), self.text.split(), limit)

    def test_chunks_end_at_sentence_boundaries(self):
        chunks = chunk(self.text, 800)
        self.assertGreater(len(chunks), 5)
        for c in chunks:
            self.assertRegex(c, r"[.!?…][\"”’')\]]*$")

    def test_paragraph_breaks_survive_inside_a_chunk(self):
        self.assertIn("\n\n", chunk(self.text, 2500)[0])

    def test_a_sentence_over_the_limit_is_split_at_clauses_then_words(self):
        long = "one, two, three, " * 20 + "end."
        chunks = chunk(long, 50)
        self.assertTrue(all(len(c) <= 50 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), long.split())
        self.assertEqual(chunk("x" * 25, 10), ["x" * 10, "x" * 10, "xxxxx"])

    def test_empty_text(self):
        self.assertEqual(chunk("", 100), [])


if __name__ == "__main__":
    unittest.main()
