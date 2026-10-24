"""Eval corpus: plain-text sources rendered to PDF and ingested like uploads.

Sources live in ``evals/docs/*.txt`` so no binaries are committed. Format:

* an optional first line ``# title: <document title>``;
* pages separated by a line containing only ``<<<PAGE>>>``;
* paragraphs separated by blank lines. Lines that ``app.core.chunking``
  recognises as headings are drawn in bold.

PDFs are rendered with reportlab at run time and then go through the real
``pdf_extract`` + ``chunking`` path, so the eval measures what users get.
Page breaks are explicit, which keeps ``must_cite_pages`` in the gold set
stable; a page that does not fit raises instead of silently reflowing.

Run ``python -m evals.corpus <out_dir>`` to write the PDFs for inspection.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.chunking import chunk_pages, heading_level
from app.core.pdf_extract import extract_pdf
from app.services.learning import ChunkData

EVALS_DIR = Path(__file__).resolve().parent
PAGE_BREAK = "<<<PAGE>>>"
TITLE_PREFIX = "# title:"

FONT, FONT_BOLD, FONT_SIZE, LEADING = "Helvetica", "Helvetica-Bold", 11, 14
MARGIN = 72
PAGE_WIDTH, PAGE_HEIGHT = 612, 792  # US letter, points


@dataclass(frozen=True)
class SourceDoc:
    title: str
    pages: list[list[str]]  # paragraphs per page


@dataclass(frozen=True)
class IngestedDoc:
    key: str  # path relative to evals/, e.g. "docs/operations.txt"
    title: str
    page_count: int
    chunks: list[ChunkData]


def parse_source(text: str, default_title: str) -> SourceDoc:
    """Split a source file into a title and per-page paragraphs."""
    lines = text.splitlines()
    title = default_title
    if lines and lines[0].startswith(TITLE_PREFIX):
        title = lines[0][len(TITLE_PREFIX):].strip() or default_title
        lines = lines[1:]
    pages: list[list[str]] = [[]]
    para: list[str] = []

    def flush() -> None:
        if para:
            pages[-1].append(" ".join(para))
            para.clear()

    for raw in lines:
        line = raw.strip()
        if line == PAGE_BREAK:
            flush()
            pages.append([])
        elif not line:
            flush()
        else:
            para.append(line)
    flush()
    return SourceDoc(title, [p for p in pages if p])


def wrap(paragraph: str, font: str, size: float, width: float) -> list[str]:
    """Greedy word wrap using real glyph widths."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    out: list[str] = []
    line = ""
    for word in paragraph.split():
        candidate = f"{line} {word}".strip()
        if line and stringWidth(candidate, font, size) > width:
            out.append(line)
            line = word
        else:
            line = candidate
    if line:
        out.append(line)
    return out


def render_pdf(doc: SourceDoc) -> bytes:
    """Draw each source page onto exactly one PDF page."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(doc.title)
    width = PAGE_WIDTH - 2 * MARGIN
    for number, paragraphs in enumerate(doc.pages, start=1):
        y = PAGE_HEIGHT - MARGIN
        for para in paragraphs:
            font = FONT_BOLD if heading_level(para) is not None else FONT
            c.setFont(font, FONT_SIZE)
            for line in wrap(para, font, FONT_SIZE, width):
                if y < MARGIN:
                    raise ValueError(f"{doc.title!r} page {number} overflows; split it with {PAGE_BREAK}")
                c.drawString(MARGIN, y, line)
                y -= LEADING
            y -= LEADING  # blank line between paragraphs
        c.showPage()
    c.save()
    return buf.getvalue()


def ingest(key: str, pdf: bytes, title: str) -> IngestedDoc:
    """Run the production extraction and chunking path over a PDF."""
    extracted = extract_pdf(pdf)
    doc_id = Path(key).stem
    chunks = [
        ChunkData(f"{doc_id}-c{c.ordinal}", c.text, c.page_start, c.page_end, c.section_label, doc_id)
        for c in chunk_pages(extracted.pages)
    ]
    return IngestedDoc(key, title, extracted.page_count, chunks)


def load_doc(key: str, root: Path = EVALS_DIR) -> IngestedDoc:
    """Build and ingest the source at ``root / key``: a .txt source rendered to PDF, or a real .pdf
    (e.g. your own documents under evals/private/, which git ignores)."""
    path = root / key
    if path.suffix.lower() == ".pdf":
        return ingest(key, path.read_bytes(), path.stem)
    source = parse_source(path.read_text(encoding="utf-8"), path.stem)
    return ingest(key, render_pdf(source), source.title)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m evals.corpus <out_dir>", file=sys.stderr)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    for src in sorted((EVALS_DIR / "docs").glob("*.txt")):
        doc = parse_source(src.read_text(encoding="utf-8"), src.stem)
        target = out / f"{src.stem}.pdf"
        target.write_bytes(render_pdf(doc))
        print(f"wrote {target} ({len(doc.pages)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
