"""Tables and formulas in extracted PDF text (P2). Pure: text in, text out.

Plain text extraction reads a table cell by cell ("Item / Units / Unit cost / Widget A / 120 ...")
and the chunker then glued those into one meaningless line. pypdf's layout mode keeps columns
aligned, so for pages that look like they contain a table (a run of very short lines in plain
text) we read the layout text, find table regions (3+ consecutive lines with the same number of
columns separated by wide gaps) and write them as pipe-delimited rows:

    | Item | Units | Unit cost | Annual demand |
    | Widget A | 120 | 4.50 | 2,400 |

Formula lines ("EOQ = sqrt(2DS / H)", "L = λW") are kept on their own line. The chunker keeps
table rows and formulas as units: never joined into a paragraph, and a table is never split
mid-row (a long table is split between rows with its header repeated).
"""
from __future__ import annotations

import re

TABLE_ROW_PREFIX = "| "
_GAP = re.compile(r"\S(?:\s{2,})\S")
_SPLIT = re.compile(r"\s{2,}")
_MATH = set("=±≤≥≈≠×÷∑∏∫√∂∆πσμλθαβγδΣΔ^")
MIN_TABLE_ROWS = 3
SHORT_LINE_RUN = 6  # this many consecutive short plain-text lines suggests a shredded table


def looks_shredded(plain: str) -> bool:
    """A run of very short lines: what plain extraction makes of a table."""
    run = 0
    for line in plain.splitlines():
        words = line.split()
        if 0 < len(words) <= 3 and len(line.strip()) <= 24:
            run += 1
            if run >= SHORT_LINE_RUN:
                return True
        else:
            run = 0
    return False


def _cells(line: str) -> list[str]:
    return [c.strip() for c in _SPLIT.split(line.strip()) if c.strip()]


def table_regions(lines: list[str]) -> list[tuple[int, int]]:
    """[(start, end_exclusive)] of table regions in layout-mode lines."""
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        n = len(_cells(lines[i])) if _GAP.search(lines[i]) else 0
        if n < 2:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and _GAP.search(lines[j]) and abs(len(_cells(lines[j])) - n) <= 1:
            j += 1
        if j - i >= MIN_TABLE_ROWS:
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def to_rows(lines: list[str]) -> list[str]:
    rows = [_cells(line) for line in lines]
    width = max(len(r) for r in rows)
    return [TABLE_ROW_PREFIX + " | ".join(r + [""] * (width - len(r))) + " |" for r in rows]


def is_formula(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 120 or s.endswith((".", ":")) and "=" not in s:
        return False
    if s.startswith(TABLE_ROW_PREFIX):
        return False
    math = sum(1 for c in s if c in _MATH)
    words = [w for w in re.findall(r"[A-Za-z]+", s) if len(w) > 3]
    return math >= 1 and ("=" in s or math >= 2) and len(words) <= 4


def structured_text(plain: str, layout: str | None) -> str:
    """Page text with tables as pipe rows. Returns `plain` unchanged when no table is found."""
    if not layout:
        return plain
    lines = layout.splitlines()
    regions = table_regions(lines)
    if not regions:
        return plain
    out: list[str] = []
    i = 0
    for start, end in regions:
        out.extend(" ".join(line.split()) for line in lines[i:start])
        out.append("")
        out.extend(to_rows(lines[start:end]))
        out.append("")
        i = end
    out.extend(" ".join(line.split()) for line in lines[i:])
    return "\n".join(out)
