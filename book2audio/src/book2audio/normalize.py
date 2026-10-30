"""Make text speakable: expand abbreviations, numbers, URLs and symbols. English only.

This is the deterministic half of "normalize for speech". It runs for every mode and backend,
costs nothing, and never drops sentences. (The optional Claude pass lives in llm.py.)
"""
import re

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALES = [(10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (10 ** 3, "thousand")]
ORDINAL_WORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
                "nine": "ninth", "twelve": "twelfth"}
MONTHS = ("January February March April May June July August September October November December").split()
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def words(n: int) -> str:
    if n < 0:
        return "minus " + words(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " hundred" + (" " + words(n % 100) if n % 100 else "")
    for size, name in SCALES:
        if n >= size:
            return words(n // size) + " " + name + (" " + words(n % size) if n % size else "")
    raise AssertionError("unreachable")


def digits(s: str) -> str:
    return " ".join(ONES[int(d)] for d in s)


def number(s: str) -> str:
    """'1,234' -> words; long or zero-padded strings (phone numbers, codes) are read digit by digit."""
    s = s.replace(",", "")
    if len(s) > 15 or (len(s) > 1 and s.startswith("0")):
        return digits(s)
    return words(int(s))


def ordinal(n: int) -> str:
    parts = re.split(r"([ -])", words(n))
    last = parts[-1]
    parts[-1] = ORDINAL_WORD.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
    return "".join(parts)


def year(n: int) -> str:
    if 2000 <= n <= 2009:
        return words(n)
    if n % 100 == 0:
        return words(n // 100) + " hundred"
    a, b = divmod(n, 100)
    return words(a) + " " + ("oh " + words(b) if b < 10 else words(b))


def roman(s: str) -> int | None:
    total = 0
    for i, ch in enumerate(s):
        v = ROMAN[ch]
        total += -v if i + 1 < len(s) and ROMAN[s[i + 1]] > v else v
    return total if 0 < total < 400 and not re.search(r"(.)\1\1\1", s) else None


ABBREVIATIONS = {
    "Mr": "Mister", "Mrs": "Missus", "Ms": "Miz", "Dr": "Doctor", "Prof": "Professor", "Sr": "Senior",
    "Jr": "Junior", "Gen": "General", "Col": "Colonel", "Capt": "Captain", "Lt": "Lieutenant",
    "Sgt": "Sergeant", "Rev": "Reverend", "Hon": "Honorable", "Gov": "Governor", "Sen": "Senator",
    "vs": "versus", "approx": "approximately", "Fig": "Figure", "Figs": "Figures", "Vol": "Volume",
    "Vols": "Volumes", "Ch": "Chapter", "pp": "pages", "Inc": "Incorporated", "Ltd": "Limited",
    "Corp": "Corporation", "Dept": "Department",
}
ABBREV_RE = re.compile(r"\b(" + "|".join(ABBREVIATIONS) + r")\.(?=\s|$)")
MONTH_ABBREV = {m[:3]: m for m in MONTHS} | {"Sept": "September"}
MONTH_RE = re.compile(r"\b(" + "|".join(MONTH_ABBREV) + r")\.?(?=\s+\d)")
SYMBOLS = {"&": " and ", "@": " at ", "+": " plus ", "=": " equals ", "×": " times ", "÷": " divided by ",
           "°": " degrees ", "±": " plus or minus ", "§": " section ", "¶": " paragraph ", "©": " copyright ",
           "→": " to ", "≤": " is at most ", "≥": " is at least ", "≠": " is not equal to ", "™": "", "®": "",
           "•": " ", "*": " ", "_": " ", "~": " ", "|": " ", "`": " ", "^": " "}
YEAR_CTX = ("in|since|by|from|until|till|before|after|of|year|circa|late|early|mid|" + "|".join(MONTHS))
CURRENCY = {"$": ("dollar", "dollars", "cent", "cents"), "€": ("euro", "euros", "cent", "cents"),
            "£": ("pound", "pounds", "penny", "pence")}
SCALE_WORD = {"k": "thousand", "m": "million", "mn": "million", "bn": "billion", "million": "million",
              "billion": "billion", "thousand": "thousand", "trillion": "trillion"}
LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", " ": " ", "­": "",
                           "​": "", "﻿": ""})


def _money(m: re.Match) -> str:
    one, many, c_one, c_many = CURRENCY[m.group(1)]
    whole = int(m.group(2).replace(",", ""))
    cents = m.group(3)
    scale = SCALE_WORD.get((m.group(4) or "").lower())
    if scale:
        return f"{words(whole)} {scale} {many}"
    out = f"{words(whole)} {one if whole == 1 else many}" if whole or not cents else ""
    if cents:
        c = int(cents.ljust(2, "0"))
        out = (out + " " if out else "") + f"{words(c)} {c_one if c == 1 else c_many}"
    return out


def _time(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    if mi == 0:
        return f"{words(h)} o'clock"
    return f"{words(h)} {'oh ' + words(mi) if mi < 10 else words(mi)}"


def _year(m: re.Match) -> str:
    ctx, n = m.group("ctx"), int(m.group("n"))
    if 1100 <= n <= 1999 or (2000 <= n <= 2009) or (2010 <= n <= 2099 and ctx):
        return (ctx + " " if ctx else "") + year(n)
    return (ctx + " " if ctx else "") + words(n)


def _decimal(m: re.Match) -> str:
    return f"{words(int(m.group(1).replace(',', '')))} point {digits(m.group(2))}"


def _url(m: re.Match) -> str:
    raw = m.group(0).rstrip(".,;:!?)'\"”’")
    host = re.sub(r"^(https?://)?(www\.)?", "", raw).split("/")[0].split("?")[0]
    return host.replace(".", " dot ").replace("-", " dash ") + m.group(0)[len(raw):]


def _roman_heading(m: re.Match) -> str:
    n = roman(m.group(2))
    return f"{m.group(1)} {words(n)}" if n else m.group(0)


def _abbr(pattern, repl, t, flags=0):
    """Replace an abbreviation whose own full stop can also end the sentence: keep that stop."""
    def f(m):
        ends = re.match(r"\s*$|\s+[A-Z“\"‘]", m.string[m.end():])
        return repl(m) + ("." if ends else "")
    return re.sub(pattern, f, t, flags=flags)


def normalize_paragraph(t: str) -> str:
    t = t.translate(LIGATURES)
    t = re.sub(r"\[(?:Illustration|Footnote)[^\]]*\]|\[\d+\]|\[[a-z]\]", "", t)  # editorial marks and note numbers
    t = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", lambda m: m.group(0).replace("@", " at ").replace(".", " dot "), t)
    t = re.sub(r"(?:https?://|www\.)\S+", _url, t)
    t = ABBREV_RE.sub(lambda m: ABBREVIATIONS[m.group(1)], t)
    t = MONTH_RE.sub(lambda m: MONTH_ABBREV[m.group(1)], t)
    t = _abbr(r"\betc\.", lambda m: "et cetera", t)
    t = re.sub(r"\be\.g\.,?", "for example,", t)
    t = re.sub(r"\bi\.e\.,?", "that is,", t)
    t = re.sub(r"\bcf\.", "compare", t)
    t = _abbr(r"\b([ap])\.m\.", lambda m: m.group(1).upper() + " M", t, re.I)
    t = _abbr(r"\b((?:[A-Z]\.){2,})", lambda m: " ".join(m.group(1).replace(".", "")), t)  # U.S. -> U S
    t = re.sub(r"\bNo\.\s*(?=\d)", "Number ", t)
    t = re.sub(r"\bpp?\.\s*(?=\d)", lambda m: "pages " if m.group(0).startswith("pp") else "page ", t)
    t = re.sub(r"#\s?(?=\d)", "number ", t)
    # Capitalised keyword only, so "the part I played" is left alone.
    t = re.sub(r"\b((?:Chapter|CHAPTER|Part|PART|Book|BOOK|Volume|VOLUME|Act|ACT|Section|SECTION|Canto|CANTO))"
               r"\s+([IVXLCDM]+)\b", _roman_heading, t)
    # numbers: most specific shapes first
    t = re.sub(r"([$€£])\s?(\d[\d,]*)(?:\.(\d{1,2}))?(?:\s?(k|mn|m|bn|thousand|million|billion|trillion)\b)?", _money, t)
    t = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s?%", lambda m: _num(m.group(1)) + " percent", t)
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time, t)
    t = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", lambda m: ordinal(int(m.group(1))), t)
    t = re.sub(r"(\d)\s?[–—]\s?(\d)", r"\1 to \2", t)
    t = re.sub(r"\b(1\d{3}|20\d{2})-(1\d{3}|20\d{2})\b", r"\1 to \2", t)
    t = re.sub(r"\b(pages?|chapters?|lines?|verses?|sections?|figures?)\s+(\d+)-(\d+)\b", r"\1 \2 to \3", t, flags=re.I)
    t = re.sub(rf"(?<![\d$€£.,-])(?:\b(?P<ctx>(?i:{YEAR_CTX}))\s+)?\b(?P<n>\d{{4}})\b(?!\d|[,.]\d)", _year, t)
    t = re.sub(r"\b(\d[\d,]*)\.(\d+)\b", _decimal, t)
    t = re.sub(r"(?<![\w.])-(?=\d)", "minus ", t)
    t = re.sub(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b", lambda m: number(m.group(0)), t)
    # dashes and symbols
    t = re.sub(r"\s*[—–]\s*", ", ", t)
    t = re.sub(r"(?<=[A-Za-z])/(?=[A-Za-z])", " or ", t)
    t = re.sub("[" + re.escape("".join(SYMBOLS)) + "]", lambda m: SYMBOLS[m.group(0)], t)
    t = re.sub(r"[\[\]{}<>]", " ", t)
    # tidy: spacing and the commas that dashes leave behind
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r",(\s*,)+", ",", t)
    t = re.sub(r",\s*([.!?”’\"'])", r"\1", t)
    return t.strip()


def _num(s: str) -> str:
    m = re.fullmatch(r"(\d[\d,]*)\.(\d+)", s)
    return _decimal(m) if m else number(s)


def normalize(text: str) -> str:
    paras = (normalize_paragraph(p) for p in text.split("\n\n"))
    return "\n\n".join(p for p in paras if p)


def sentence_end(title: str) -> str:
    """A chapter title read aloud needs a full stop so the voice pauses after it."""
    title = title.strip()
    return title if title.endswith((".", "!", "?", "…")) else title + "."
