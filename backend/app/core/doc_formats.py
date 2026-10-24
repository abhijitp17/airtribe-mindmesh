"""Library documents beyond PDF (P3): Word (.docx), plain text, Markdown and HTML.

Detected from the bytes, not the file name (a renamed file can't slip through as another type).
Each becomes the same `ExtractionResult` the PDF path produces, so chunking, citations, concepts
and quizzes work unchanged:
  * Headings become Markdown-style "#" lines, which the chunker reads as section headings
    (Word "Heading 1-3" styles, HTML h1-h3, Markdown #).
  * Word tables and Markdown/HTML tables become pipe rows (as for PDFs, core.structure).
  * Text is split into "pages" of about PAGE_CHARS at paragraph breaks, so citations point
    somewhere specific ("p. 3" is the third part of the file).
"""
from __future__ import annotations

import io
import re
import zipfile

from .pdf_extract import MIN_CHARS_PER_PAGE, ExtractionResult, PageText, PdfExtractionError
from .structure import TABLE_ROW_PREFIX
from .upload_safety import UploadRejected, check_zip_container

PAGE_CHARS = 3000
FORMATS = ("pdf", "docx", "html", "markdown", "text")
MEDIA_TYPES = {"pdf": "application/pdf", "html": "text/html; charset=utf-8", "markdown": "text/markdown; charset=utf-8",
               "text": "text/plain; charset=utf-8",
               "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def detect(data: bytes, filename: str | None = None) -> str | None:
    """The document's format, or None when it isn't one we read."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                return "docx" if "word/document.xml" in zf.namelist() else None
        except zipfile.BadZipFile:
            return None
    text = _decode(data)
    if text is None:
        return None
    head = text[:4000].lower()
    name = (filename or "").lower()
    if name.endswith((".html", ".htm")) or "<html" in head or "<body" in head or "<!doctype html" in head:
        return "html"
    if name.endswith((".md", ".markdown")) or re.search(r"^#{1,6} \S", text[:4000], re.M):
        return "markdown"
    return "text"


def _decode(data: bytes) -> str | None:
    if b"\x00" in data[:4096]:
        return None  # binary
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    text = data.decode("latin-1")
    printable = sum(c.isprintable() or c in "\n\r\t" for c in text[:4000])
    return text if printable >= 0.95 * min(len(text), 4000) else None


# ---------------------------------------------------------------- to text with structure

def _docx_markdown(data: bytes) -> tuple[str, str | None]:
    try:
        check_zip_container(data)
    except UploadRejected as exc:
        raise PdfExtractionError(exc.message) from exc
    try:
        import docx  # python-docx
        d = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise PdfExtractionError("Could not read this Word file. Re-save it from Word as .docx and try again.") from exc
    lines: list[str] = []
    title = (d.core_properties.title or "").strip() or None
    body = d.element.body
    paras = {p._p: p for p in d.paragraphs}
    tables = {t._tbl: t for t in d.tables}
    for child in body.iterchildren():  # paragraphs and tables in document order
        if child in paras:
            p = paras[child]
            text = " ".join(p.text.split())
            style = str(p.style.name if p.style is not None else "").lower()
            m = re.match(r"heading (\d)", style)
            if text and (m or style == "title"):
                lines += ["", "#" * min(int(m.group(1)) if m else 1, 3) + " " + text, ""]
            elif text:
                lines.append(("• " if style.startswith("list") else "") + text)
            else:
                lines.append("")
        elif child in tables:
            lines.append("")
            for row in tables[child].rows:
                cells = [" ".join(c.text.split()) for c in row.cells]
                lines.append(TABLE_ROW_PREFIX + " | ".join(cells) + " |")
            lines.append("")
    return "\n".join(lines), title


def _html_markdown(text: str) -> tuple[str, str | None]:
    from .job_fetch import html_to_text

    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = " ".join(m.group(1).split()) if m else None
    text = re.sub(r"<h([1-3])[^>]*>", lambda h: "\n\n" + "#" * int(h.group(1)) + " ", text, flags=re.I)
    text = re.sub(r"</h[1-3]>", "\n\n", text, flags=re.I)
    text = re.sub(r"<tr[^>]*>", "\n" + TABLE_ROW_PREFIX, text, flags=re.I)
    text = re.sub(r"</t[dh]>", " | ", text, flags=re.I)
    return html_to_text(text), title


_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def _markdown_clean(text: str) -> str:
    out = []
    for line in text.splitlines():
        s = _MD_LINK.sub(r"\1", line)
        if re.match(r"^\s*\|?\s*:?-{3,}", s):  # table separator row
            continue
        if s.strip().startswith("|"):
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            s = TABLE_ROW_PREFIX + " | ".join(cells) + " |"
        else:
            s = re.sub(r"(\*\*|__|`)", "", s)
        out.append(s.rstrip())
    return "\n".join(out)


def _pages(text: str) -> list[PageText]:
    paras = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    pages, buf = [], ""
    for p in paras:
        if buf and len(buf) + len(p) > PAGE_CHARS:
            pages.append(buf)
            buf = ""
        buf = f"{buf}\n\n{p}" if buf else p
    if buf.strip():
        pages.append(buf)
    return [PageText(i, t.strip(), len(t.strip()), len(t.strip()) < MIN_CHARS_PER_PAGE)
            for i, t in enumerate(pages, start=1) if t.strip()]


def extract_text_document(data: bytes, fmt: str, max_pages: int = 1000) -> ExtractionResult:
    """Word, HTML, Markdown or text -> pages. Raises PdfExtractionError with a user-facing message."""
    if fmt == "docx":
        text, title = _docx_markdown(data)
    else:
        raw = _decode(data)
        if raw is None:
            raise PdfExtractionError("This file isn't readable text.")
        if fmt == "html":
            text, title = _html_markdown(raw)
        elif fmt == "markdown":
            text, title = _markdown_clean(raw), None
        else:
            text, title = raw, None
    pages = _pages(text)
    if not pages:
        raise PdfExtractionError("The file has no text.")
    if len(pages) > max_pages:
        raise PdfExtractionError(f"The file is too long ({len(pages)} parts; the limit is {max_pages}).")
    if title is None:
        first = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.strip()), "")
        title = first[:120] or None if fmt in ("markdown", "docx", "html") else None
    return ExtractionResult(pages=pages, page_count=len(pages), title=title)
