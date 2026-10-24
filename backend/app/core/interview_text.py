"""Text extraction for resumes and job descriptions (PRD §7.1).

Users bring a resume as a PDF, a DOCX or pasted text, and a JD as pasted text.
Everything downstream (parsing, verbatim-quote validation) works on the plain
text returned here, so this module is the single place that decides what the
"source text" is. The parser validates every extracted bullet against exactly
this text, which is why normalisation must be stable and idempotent.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field

from .pdf_extract import PdfExtractionError, extract_pdf
from .upload_safety import UploadRejected, check_zip_container

MAX_RESUME_CHARS = 30_000
MAX_JD_CHARS = 20_000
MIN_CHARS = 80

# PDF bullet glyphs (incl. Symbol/Wingdings private-use code points) folded to one
# canonical bullet so the heuristic parser and the prompts see a single marker.
_BULLET_GLYPHS = "●▪■◦‣⁃∙·►➢❖"
_BULLET_RE = re.compile(f"[{_BULLET_GLYPHS}]")
# Fonts without a Unicode map (Symbol, Wingdings) extract bullets as control or
# private-use characters; at the start of a line they can only be a bullet.
_GLYPH_BULLET_RE = re.compile(r"^[\x01-\x08\x0b\x0c\x0e-\x1f\x7f\ue000-\uf8ff\ufffd]+\s*", re.M)
_CONTROL_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DOCX_MAGIC = b"PK\x03\x04"


class InputError(ValueError):
    """The input cannot be used; the message tells the user what to do instead."""


class UnsupportedFileType(InputError):
    pass


@dataclass
class ExtractedText:
    text: str
    warnings: list[str] = field(default_factory=list)


def normalize_source(text: str) -> str:
    """Canonical source text: NFKC, unified bullets, tidy whitespace, line structure kept.

    Line breaks are preserved because section headers and bullets are line-based;
    only runs of spaces and blank lines are collapsed.
    """
    text = unicodedata.normalize("NFKC", text or "").replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = _BULLET_RE.sub("•", text)
    text = _CONTROL_RE.sub("", _GLYPH_BULLET_RE.sub("• ", text))
    lines = [re.sub(r" {2,}", " ", ln).strip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _cap(text: str, limit: int, what: str, warnings: list[str]) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    warnings.append(
        f"The {what} is long; only the first {limit:,} characters were analysed. "
        "Remove older or less relevant sections if something is missing."
    )
    return text[: cut if cut > limit // 2 else limit].rstrip()


def _require_enough(text: str, what: str) -> None:
    if len(text) < MIN_CHARS:
        raise InputError(
            f"The {what} has too little text to analyse ({len(text)} characters). "
            "Paste the full text or upload a text-based file."
        )


def _pdf_text(data: bytes, warnings: list[str]) -> str:
    try:
        result = extract_pdf(data, max_pages=20)
    except PdfExtractionError as exc:
        raise InputError(f"{exc} Try exporting the resume again, or paste its text instead.") from exc
    text = "\n".join(p.text for p in result.pages)
    if result.needs_attention:
        if len(text.strip()) < MIN_CHARS:
            raise InputError(
                "This PDF looks scanned (no selectable text). Export it from your editor as a "
                "text-based PDF or DOCX, or paste the text instead."
            )
        warnings.append("Some pages had little selectable text; check that nothing is missing.")
    return text


def _docx_paragraph_text(paragraph) -> str:
    """Prefix list paragraphs with a bullet: Word stores bullets as numbering, not text."""
    text = paragraph.text
    p_pr = paragraph._p.pPr
    is_list = (p_pr is not None and p_pr.numPr is not None) or (paragraph.style is not None and str(paragraph.style.name).lower().startswith("list"))
    return f"• {text}" if is_list and text.strip() else text


def _docx_text(data: bytes) -> str:
    try:
        check_zip_container(data)  # zip-bomb limits before python-docx unpacks every part
    except UploadRejected as exc:
        raise InputError(exc.message) from exc
    try:
        import docx  # python-docx
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - any parse failure is a user-facing input problem
        raise InputError("Could not read this DOCX file. Re-save it from Word or paste the text instead.") from exc
    lines = [_docx_paragraph_text(p) for p in document.paragraphs]
    # Many resume templates lay out sections in tables; read cells row by row.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                lines.extend(_docx_paragraph_text(p) for p in cell.paragraphs)
    return "\n".join(lines)


def extract_resume_file(data: bytes, filename: str | None) -> ExtractedText:
    """Extract resume text from an uploaded PDF or DOCX, detected by content, not name."""
    warnings: list[str] = []
    if data.startswith(b"%PDF-"):
        raw = _pdf_text(data, warnings)
    elif data.startswith(_DOCX_MAGIC):
        raw = _docx_text(data)  # a non-Word zip fails inside with an actionable message
    else:
        name = f" ({filename})" if filename else ""
        raise UnsupportedFileType(f"Unsupported file type{name}. Upload a PDF or DOCX resume, or paste the text instead.")
    text = normalize_source(raw)
    _require_enough(text, "resume")
    return ExtractedText(_cap(text, MAX_RESUME_CHARS, "resume", warnings), warnings)


def prepare_text(text: str, kind: str) -> ExtractedText:
    """Normalise pasted text. `kind` is "resume" or "job description"."""
    warnings: list[str] = []
    clean = normalize_source(text)
    _require_enough(clean, kind)
    limit = MAX_RESUME_CHARS if kind == "resume" else MAX_JD_CHARS
    return ExtractedText(_cap(clean, limit, kind, warnings), warnings)
