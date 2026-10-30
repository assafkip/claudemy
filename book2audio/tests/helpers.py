"""Shared test setup: puts src/ on the path and builds tiny EPUBs."""
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
FIXTURES = HERE / "fixtures"

WORDS = "The quick brown fox jumps over the lazy dog while the river keeps running toward the sea. " * 3


def make_epub(path, pages, toc, title="Test Book", author="Ann Author"):
    """pages: {file name: <body> html}; toc: [(label, 'file' or 'file#id')]. EPUB 3 with a nav document."""
    nav = "".join(f'<li><a href="{href}">{label}</a></li>' for label, href in toc)
    items = "".join(f'<item id="p{i}" href="{n}" media-type="application/xhtml+xml"/>' for i, n in enumerate(pages))
    spine = "".join(f'<itemref idref="p{i}"/>' for i in range(len(pages)))
    opf = (f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
           f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title>'
           f'<dc:creator>{author}</dc:creator></metadata><manifest>'
           f'<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>{items}'
           f'</manifest><spine>{spine}</spine></package>')
    wrap = ('<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
            '<head><title>x</title></head><body {attrs}>{body}</body></html>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", wrap.format(attrs="", body=f'<nav epub:type="toc"><ol>{nav}</ol></nav>'))
        for name, body in pages.items():
            attrs = ""
            if isinstance(body, tuple):  # (epub:type of the body, html)
                attrs, body = f'epub:type="{body[0]}"', body[1]
            z.writestr(f"OEBPS/{name}", wrap.format(attrs=attrs, body=body))
    return path
