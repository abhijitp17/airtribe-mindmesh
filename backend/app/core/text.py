"""Shared text normalization and tokenization helpers."""
from __future__ import annotations

import re
import unicodedata

STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has have
    how i if in into is it its may me might my no not of on or our out over should so
    such than that the their them then there these they this those to too under up us
    was we were what when where which while who whom why will with would you your
    about also any each more most other some very just only own same both few""".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")


def normalize(text: str) -> str:
    """Lowercase, fold unicode (ligatures, smart quotes), collapse whitespace."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("­", "")  # soft hyphen
    text = re.sub(r"-\s*\n\s*", "", text)  # de-hyphenate line breaks
    return re.sub(r"\s+", " ", text).strip().lower()


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    tokens = _TOKEN_RE.findall(normalize(text))
    if drop_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS]
    return [stem(t) for t in tokens]


def stem(token: str) -> str:
    """Tiny suffix stripper; good enough for lexical recall in English."""
    if len(token) <= 4 or token.isdigit():
        return token
    for suffix in ("ations", "ation", "ingly", "ings", "ing", "edly", "ies", "ed", "es", "ly", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            base = token[: -len(suffix)]
            return base + "y" if suffix == "ies" else base
    return token


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))
