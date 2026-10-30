"""Book model shared by the EPUB and PDF readers, plus front/back-matter detection."""
import re
from dataclasses import dataclass


class B2AError(Exception):
    """A problem the user can act on; the CLI prints the message without a traceback."""


@dataclass
class Chapter:
    title: str
    text: str
    skip: str | None = None  # why the chapter is not narrated; None means narrate it


@dataclass
class Book:
    title: str
    author: str
    chapters: list[Chapter]
    cover: bytes | None = None
    cover_ext: str = "jpg"


MIN_WORDS = 20  # below this a "chapter" is a title page, an epigraph or a stray heading
# Whole-title matches, so a real chapter called "Cover Story" or "Notes from Underground" survives.
_EXACT = re.compile(r"table of contents|contents|cover|index|notes|endnotes|credits|references|bibliography|"
                    r"copyright|colophon|imprint|title page|half ?title|dedication|permissions|"
                    r"acknowledg\w*|advertisements?|newsletter")
_PREFIX = re.compile(r"copyright|also by|other books|about the author|praise for|index of|"
                     r"project gutenberg|the full project gutenberg")


def skip_reason(title: str, text: str) -> str | None:
    t = " ".join(re.sub(r"[^\w\s]", " ", title.lower()).split())
    if _EXACT.fullmatch(t) or _PREFIX.match(t):
        return "front/back matter"
    words = len(text.split())
    return f"too short ({words} words)" if words < MIN_WORDS else None
