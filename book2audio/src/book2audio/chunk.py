"""Split text into chunks at sentence boundaries, each within a TTS backend's character limit."""
import re

SENTENCE = re.compile(r".+?(?:[.!?…]+[\"”’')\]]*(?:\s+|$)|$)", re.S)
CLAUSE = re.compile(r".+?(?:[,;:]\s+|$)", re.S)


def _fit(parts: list[str], limit: int, sep: str) -> list[str]:
    """Greedily pack parts into pieces of at most `limit` characters."""
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(sep) + len(p) > limit:
            out.append(cur)
            cur = ""
        cur = cur + sep + p if cur else p
    return out + [cur] if cur else out


def _split_long(sentence: str, limit: int) -> list[str]:
    """A sentence over the limit: cut at clause boundaries, then at spaces, then hard."""
    pieces = []
    for clause in _fit([c.strip() for c in CLAUSE.findall(sentence) if c.strip()], limit, " "):
        if len(clause) <= limit:
            pieces.append(clause)
            continue
        for word in clause.split():
            while len(word) > limit:  # shortcut: a single unbroken word over the limit is cut mid-word
                pieces.append(word[:limit])
                word = word[limit:]
            pieces.append(word)
    return _fit(pieces, limit, " ")


def sentences(paragraph: str, limit: int):
    for s in SENTENCE.findall(paragraph):
        s = s.strip()
        if s:
            yield from ([s] if len(s) <= limit else _split_long(s, limit))


def chunk(text: str, limit: int) -> list[str]:
    """Chunks of at most `limit` characters; paragraphs stay separated by a blank line inside a chunk."""
    chunks, cur = [], ""
    for par in text.split("\n\n"):
        first = True
        for piece in sentences(par.strip(), limit):
            sep = "" if not cur else ("\n\n" if first else " ")
            if cur and len(cur) + len(sep) + len(piece) > limit:
                chunks.append(cur)
                cur, sep = "", ""
            cur += sep + piece
            first = False
    return chunks + [cur] if cur else chunks
