"""Tables and formulas: detection, structured page text, chunking that keeps them whole."""
import io

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.core import structure as st
from app.core.chunking import MAX_CHARS, chunk_pages
from app.core.pdf_extract import PageText, extract_pdf

ROWS = [["Item", "Units", "Unit cost", "Annual demand"], ["Widget A", "120", "4.50", "2,400"],
        ["Widget B", "80", "12.00", "1,100"], ["Gear C", "45", "30.25", "600"]]


def table_pdf(rows=ROWS, prose_after=True) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 740
    for line in ["2.1 Inventory costs", "Holding cost depends on the unit value and the carrying rate per year.", ""]:
        c.drawString(72, y, line)
        y -= 16
    for r in rows:
        for x, cell in zip([72, 200, 290, 400], r):
            c.drawString(x, y, cell)
        y -= 16
        if y < 80:
            c.showPage()
            y = 740
    if prose_after:
        y -= 10
        for line, x in [("The economic order quantity is:", 72), ("EOQ = sqrt(2DS / H)", 110),
                        ("where D is annual demand, S the order cost and H the holding cost per unit.", 72)]:
            c.drawString(x, y, line)
            y -= 16
    c.showPage()
    c.save()
    return buf.getvalue()


def test_shredded_detection():
    assert st.looks_shredded("\n".join(["Item", "Units", "Cost", "Widget", "120", "4.50", "Gear"]))
    assert not st.looks_shredded("A normal paragraph of prose that goes on.\nAnother long line of normal text here.")


def test_table_regions_and_rows():
    lines = ["Intro text here", "Item        Units     Cost", "Widget      120       4.50",
             "Gear        45        30.25", "Some prose after the table ends."]
    assert st.table_regions(lines) == [(1, 4)]
    assert st.to_rows(lines[1:4])[1] == "| Widget | 120 | 4.50 |"
    assert st.table_regions(["A  B", "C  D"]) == [], "two rows aren't a table"


@pytest.mark.parametrize("line, expected", [
    ("EOQ = sqrt(2DS / H)", True), ("L = λW", True), ("σ² = Σ(x − μ)² / n", True),
    ("Revenue grew 5% in 2024.", False), ("The holding cost is described below:", False),
    ("Little's Law states that the average work in process equals throughput times cycle time = TH × CT", False),
    ("| a | b |", False),
])
def test_is_formula(line, expected):
    assert st.is_formula(line) is expected


def test_pdf_table_becomes_rows_and_formula_keeps_its_line():
    r = extract_pdf(table_pdf())
    text = r.pages[0].text
    assert "| Item | Units | Unit cost | Annual demand |" in text and "| Gear C | 45 | 30.25 | 600 |" in text
    chunks = chunk_pages(r.pages)
    body = "\n".join(c.text for c in chunks)
    assert "| Widget A | 120 | 4.50 | 2,400 |\n| Widget B | 80 | 12.00 | 1,100 |" in body, "rows stay on their own lines"
    assert "\nEOQ = sqrt(2DS / H)\n" in body, "formula not merged into prose"
    assert "Holding cost depends on the unit value and the carrying rate per year." in body


def test_prose_pages_are_unchanged():
    plain = "A heading\nOne line of ordinary prose that is long enough.\nAnother ordinary line of prose here."
    assert st.structured_text(plain, None) == plain
    assert st.structured_text(plain, plain) == plain


def test_a_long_table_splits_between_rows_with_its_header():
    header = "| Item | Units | Unit cost | Annual demand |"
    rows = [header] + [f"| Part {i:03d} | {i} | {i * 1.5:.2f} | {i * 100} |" for i in range(120)]
    chunks = chunk_pages([PageText(1, "\n".join(rows), 5000, False)])
    assert len(chunks) > 1
    for c in chunks:
        lines = c.text.split("\n")
        assert lines[0] == header and all(line.startswith("| ") and line.endswith(" |") for line in lines)
        assert len(c.text) <= MAX_CHARS
    seen = [line for c in chunks for line in c.text.split("\n")[1:]]
    assert seen == rows[1:], "every row once, in order"
