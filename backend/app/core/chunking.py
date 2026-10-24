"""Structure-aware chunking that preserves page anchors.

Every chunk records page_start/page_end and the heading path it sits under,
so any answer built from it can cite "p. 42, Chapter 3 > Variability"
(FR-012). We split on paragraph boundaries and never in the middle of a line,
which keeps formulas and table rows intact far better than fixed windows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pdf_extract import PageText
from .structure import TABLE_ROW_PREFIX, is_formula

TABLE, FORMULA = -1, -2
_MD_HEADING = re.compile(r"^(#{1,6})\s+(\S.{0,88})$")  # unit kinds from _paragraphs (positive values are heading levels)

TARGET_CHARS = 1200
MAX_CHARS = 2000
MIN_CHARS = 200

_NUMBERED_HEADING = re.compile(r"^(?:chapter|section|part)?\s*\d+(?:\.\d+){0,3}\.?\s+[A-Z][^.!?]{2,80}$", re.I)
_CHAPTER_WORD = re.compile(r"^(chapter|part|appendix)\s+[\dIVXLC]+\b", re.I)


@dataclass
class Chunk:
    ordinal: int
    text: str
    page_start: int
    page_end: int
    section_path: list[str] = field(default_factory=list)

    @property
    def section_label(self) -> str:
        return " > ".join(self.section_path)


def heading_level(line: str) -> int | None:
    """Return a heading level (1 = top) or None if the line is body text."""
    s = line.strip()
    if not s or len(s) > 90 or len(s) < 3:
        return None
    if s.endswith((".", ",", ";", ":")) and not _CHAPTER_WORD.match(s):
        return None
    if _CHAPTER_WORD.match(s):
        return 1
    m = _NUMBERED_HEADING.match(s)
    if m:
        number = re.match(r"^(?:chapter|section|part)?\s*(\d+(?:\.\d+)*)", s, re.I)
        depth = number.group(1).count(".") + 1 if number else 1
        return min(depth, 3)
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters) and len(s.split()) <= 8:
        return 1
    return None


def _paragraphs(pages: list[PageText]) -> list[tuple[str, int, int | None]]:
    """Yield (text, page_number, heading_level) units in reading order."""
    units: list[tuple[str, int, int | None]] = []
    for page in pages:
        buf: list[str] = []

        def flush() -> None:
            if buf:
                units.append((" ".join(buf).strip(), page.page_number, None))
                buf.clear()

        table: list[str] = []

        def flush_table() -> None:
            if table:
                units.append(("\n".join(table), page.page_number, TABLE))
                table.clear()

        for raw in page.text.splitlines():
            line = raw.strip()
            if line.startswith(TABLE_ROW_PREFIX):  # a table row: kept with its table, never joined into prose
                flush()
                table.append(line)
                continue
            flush_table()
            if not line:
                flush()
                continue
            md = _MD_HEADING.match(line)
            if md:  # "# Heading" from Word, HTML and Markdown documents (core.doc_formats)
                flush()
                units.append((md.group(2).strip(), page.page_number, min(len(md.group(1)), 3)))
                continue
            if is_formula(line):  # a formula stays on its own line
                flush()
                units.append((line, page.page_number, FORMULA))
                continue
            level = heading_level(line)
            if level is not None:
                flush()
                units.append((line, page.page_number, level))
            else:
                buf.append(line)
        flush()
        flush_table()
    return [u for u in units if u[0]]


def chunk_pages(pages: list[PageText]) -> list[Chunk]:
    chunks: list[Chunk] = []
    path: list[str] = []
    cur_text: list[str] = []
    cur_start: int | None = None
    cur_end: int | None = None
    cur_path: list[str] = []

    def emit() -> None:
        nonlocal cur_text, cur_start, cur_end
        body = "\n".join(cur_text).strip()
        if body and cur_start is not None:
            chunks.append(
                Chunk(len(chunks), body, cur_start, cur_end or cur_start, list(cur_path))
            )
        cur_text, cur_start, cur_end = [], None, None

    for text, page_no, level in _paragraphs(pages):
        if level is not None and level > 0:
            if sum(len(t) for t in cur_text) >= MIN_CHARS:
                emit()
            path = path[: level - 1] + [text]
            if not cur_text:
                cur_path = list(path)
            continue

        size = sum(len(t) for t in cur_text)
        if cur_text and size + len(text) > TARGET_CHARS:
            emit()
        if not cur_text:
            cur_path = list(path)
            cur_start = page_no
        # A long table is split between rows (header repeated); a long paragraph on sentence boundaries.
        if level == TABLE:
            pieces = _split_table(text) if len(text) > MAX_CHARS else [text]
        else:
            pieces = _split_long(text) if len(text) > MAX_CHARS else [text]
        for i, piece in enumerate(pieces):
            if i > 0:
                emit()
                cur_path, cur_start = list(path), page_no
            cur_text.append(piece)
            cur_end = page_no
    emit()
    return chunks


def _split_table(text: str) -> list[str]:
    rows = text.split("\n")
    header, body = rows[0], rows[1:]
    out: list[str] = []
    cur = [header]
    for r in body:
        if len("\n".join(cur)) + len(r) > TARGET_CHARS and len(cur) > 1:
            out.append("\n".join(cur))
            cur = [header]
        cur.append(r)
    out.append("\n".join(cur))
    return out


def _split_long(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out: list[str] = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + len(s) > TARGET_CHARS:
            out.append(buf.strip())
            buf = ""
        buf += s + " "
        while len(buf) > MAX_CHARS:  # pathological: no sentence breaks
            out.append(buf[:MAX_CHARS])
            buf = buf[MAX_CHARS:]
    if buf.strip():
        out.append(buf.strip())
    return out
