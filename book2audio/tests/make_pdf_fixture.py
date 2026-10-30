"""Builds tests/fixtures/alice-excerpt.pdf from the first chapters of Project Gutenberg #11
(public domain). Run once; the PDF is committed, so the tests do not need reportlab.

    pip install reportlab && python tests/make_pdf_fixture.py

The PDF is laid out like a real book on purpose: running headers that alternate by page,
page numbers, an indented first line per paragraph, bookmarks, a footnote with a superscript
marker, and words hyphenated at line ends. test_pdf.py checks that all of that is undone.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

CHAPTERS = 3
WORDS_PER_CHAPTER = 800
FOOTNOTE = "1 Footnote text that must never be read aloud, written in a smaller type."
MARKER = "<fn>"  # placeholder word the layout draws as a superscript 1 glued to the previous word


def excerpt():
    """[(chapter heading, [paragraph text])]: the same words the PDF is built from."""
    from book2audio import epub
    book = epub.load(HERE / "fixtures" / "alice.epub")
    out = []
    for ch in [c for c in book.chapters if not c.skip][:CHAPTERS]:
        paras, count = [], 0
        for p in ch.text.split("\n\n"):
            paras.append(p)
            count += len(p.split())
            if count >= WORDS_PER_CHAPTER:
                break
        out.append((ch.title, paras))
    return out


def build(target):
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    W, H = LETTER
    LEFT, RIGHT, TOP, BOTTOM = 72, W - 72, H - 110, 100
    FONT, SIZE, LEAD = "Times-Roman", 11, 15
    SPACE = stringWidth(" ", FONT, SIZE)
    c = canvas.Canvas(str(target), pagesize=LETTER)
    c.setTitle("Alice's Adventures in Wonderland (excerpt)")
    c.setAuthor("Lewis Carroll")
    st = {"page": 0, "y": 0.0, "bottom": BOTTOM, "note": False}

    def wid(w):
        return stringWidth("1", FONT, 7) if w == MARKER else stringWidth(w, FONT, SIZE)

    def finish_page():
        c.setFont(FONT, 9)
        c.drawCentredString(W / 2, H - 50, "LEWIS CARROLL" if st["page"] % 2 == 0 else "ALICE'S ADVENTURES IN WONDERLAND")
        c.drawCentredString(W / 2, 40, str(st["page"]))
        if st["note"]:
            c.setFont(FONT, 8)
            c.drawString(LEFT, 85, FOOTNOTE)

    def new_page(note=False):
        if st["page"]:
            finish_page()
            c.showPage()
        st.update(page=st["page"] + 1, y=TOP, bottom=BOTTOM + (25 if note else 0), note=note)

    def draw_line(words, x):
        if st["y"] < st["bottom"]:
            new_page()
        c.setFont(FONT, SIZE)
        for w in words:
            if w == MARKER:
                x -= SPACE
                c.setFont(FONT, 7)
                c.drawString(x, st["y"] + 4, "1")
                c.setFont(FONT, SIZE)
                x += wid(w) + SPACE
            else:
                c.drawString(x, st["y"], w)
                x += wid(w) + SPACE
        st["y"] -= LEAD

    def paragraph(words, indent=18):
        x0, line, used, i = LEFT + indent, [], 0.0, 0
        words = list(words)
        while i < len(words):
            w = words[i]
            if used + wid(w) <= RIGHT - x0:
                line.append(w)
                used += wid(w) + SPACE
                i += 1
                continue
            cut = 0
            if len(w) >= 9 and w.isalpha():  # hyphenate long plain words at the line end
                cut = next((k for k in range(len(w) - 3, 2, -1)
                            if used + stringWidth(w[:k] + "-", FONT, SIZE) <= RIGHT - x0), 0)
            if cut:
                line.append(w[:cut] + "-")
                words[i] = w[cut:]
            draw_line(line, x0)
            x0, line, used = LEFT, [], 0.0
        if line:
            draw_line(line, x0)

    new_page()  # title page: no bookmark, no body text
    c.setFont("Times-Bold", 26)
    c.drawCentredString(W / 2, H / 2, "Alice's Adventures in Wonderland")
    c.setFont(FONT, 14)
    c.drawCentredString(W / 2, H / 2 - 30, "Lewis Carroll")

    for n, (heading, paras) in enumerate(excerpt()):
        new_page(note=(n == 0))
        c.bookmarkPage(f"ch{n}")
        c.addOutlineEntry(heading, f"ch{n}", level=0)
        label, _, subtitle = heading.partition(". ")
        c.setFont("Times-Bold", 20)
        c.drawString(LEFT, st["y"], label.upper() + ".")
        c.drawString(LEFT, st["y"] - 26, subtitle)
        st["y"] -= 70
        for p_index, para in enumerate(paras):
            words = para.split()
            if n == 0 and p_index == 0:
                words.insert(12, MARKER)
            paragraph(words)
    finish_page()
    c.save()


if __name__ == "__main__":
    out = HERE / "fixtures" / "alice-excerpt.pdf"
    build(out)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
