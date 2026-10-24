"""PDF text extraction with per-page quality signals.

Strategy (PRD 6.2 / 11.2): cheap text-layer extraction first. Pages with
little or no extractable text are flagged as likely scans so the user is
warned (FR-013) instead of silently getting bad lessons. OCR text for those
pages (core.ocr) is merged in by `apply_ocr` / `merge_ocr` during ingestion.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Callable

from pypdf import PdfReader

from .structure import looks_shredded, structured_text
from pypdf.errors import PdfReadError

MIN_CHARS_PER_PAGE = 80
LOW_QUALITY_PAGE_RATIO = 0.3


class PdfExtractionError(Exception):
    """Raised for files that cannot be processed at all."""


@dataclass
class PageText:
    page_number: int  # 1-based, matches what users see in a PDF viewer
    text: str
    char_count: int
    low_text: bool


@dataclass
class ExtractionResult:
    pages: list[PageText]
    page_count: int
    title: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def low_text_pages(self) -> list[int]:
        return [p.page_number for p in self.pages if p.low_text]

    @property
    def needs_attention(self) -> bool:
        if not self.pages:
            return True
        return len(self.low_text_pages) / len(self.pages) > LOW_QUALITY_PAGE_RATIO


def extract_pdf(data: bytes, max_pages: int = 1000,
                on_page: Callable[[list[PageText], int], None] | None = None) -> ExtractionResult:
    """Extract text page by page. ``on_page(pages_so_far, page_count)`` runs after each page (progress)."""
    if not data.startswith(b"%PDF-"):
        raise PdfExtractionError("File is not a PDF (missing %PDF header).")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise PdfExtractionError("PDF is password-protected.") from exc
        page_count = len(reader.pages)
    except PdfReadError as exc:
        raise PdfExtractionError(f"Could not read PDF: {exc}") from exc

    if page_count == 0:
        raise PdfExtractionError("PDF has no pages.")
    if page_count > max_pages:
        raise PdfExtractionError(
            f"PDF has {page_count} pages; the current limit is {max_pages}."
        )

    pages: list[PageText] = []
    warnings: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - one bad page must not kill the document
            text = ""
            warnings.append(f"Page {i}: text extraction failed.")
        text = text.replace("\x00", "")
        if looks_shredded(text):  # P2: a table read cell by cell; recover its rows from layout mode
            try:
                text = structured_text(text, (page.extract_text(extraction_mode="layout") or "").replace("\x00", ""))
            except Exception:  # noqa: BLE001 - layout mode is best-effort; plain text still works
                pass
        stripped = text.strip()
        pages.append(
            PageText(
                page_number=i,
                text=text,
                char_count=len(stripped),
                low_text=len(stripped) < MIN_CHARS_PER_PAGE,
            )
        )
        if on_page is not None:
            on_page(pages, page_count)

    title = None
    try:
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title).strip() or None
    except Exception:  # noqa: BLE001
        pass

    result = ExtractionResult(pages=pages, page_count=page_count, title=title, warnings=warnings)
    if result.needs_attention:
        result.warnings.append(_scanned_warning(result))
    return result


def _scanned_warning(result: ExtractionResult, ocr_tried: bool = False) -> str:
    tail = (
        "OCR could not recover them; answers may be incomplete."
        if ocr_tried
        else "The file may be scanned; answers may be incomplete until OCR is supported."
    )
    return f"{len(result.low_text_pages)} of {result.page_count} pages have little or no text. {tail}"


# ---------- OCR merge (pure; used by services.ingestion) ----------

def merge_ocr(pages: list[PageText], ocr_map: dict[int, str]) -> tuple[list[PageText], list[int]]:
    """Swap in OCR text for low-text pages. Returns (new pages, OCR'd page numbers).

    A page is replaced only if it was ``low_text`` and the OCR text clears the
    same MIN_CHARS_PER_PAGE bar used to flag it. So OCR never overwrites a
    good text layer, and OCR noise (a few stray glyphs) doesn't count as
    recovering the page. Pure and idempotent: merging the same map twice gives
    the same result, because replaced pages are no longer low_text.
    """
    out: list[PageText] = []
    applied: list[int] = []
    for p in pages:
        text = ocr_map.get(p.page_number)
        if p.low_text and text is not None:
            text = text.replace("\x00", "")
            stripped = text.strip()
            if len(stripped) >= MIN_CHARS_PER_PAGE:
                out.append(PageText(p.page_number, text, len(stripped), low_text=False))
                applied.append(p.page_number)
                continue
        out.append(p)
    return out, applied


def apply_ocr(result: ExtractionResult, ocr_map: dict[int, str]) -> tuple[ExtractionResult, list[int]]:
    """``merge_ocr`` on a whole result, with the scanned-file warning recomputed.

    ``needs_attention`` / ``low_text_pages`` are properties, so they follow
    the merged pages automatically. Only the warning text has to be rebuilt.
    """
    pages, applied = merge_ocr(result.pages, ocr_map)
    merged = ExtractionResult(pages=pages, page_count=result.page_count, title=result.title)
    merged.warnings = [w for w in result.warnings if "little or no text" not in w]
    if merged.needs_attention:
        merged.warnings.append(_scanned_warning(merged, ocr_tried=bool(ocr_map) or bool(applied)))
    return merged, applied


def format_page_list(pages: list[int]) -> str:
    """[1, 2, 3, 7, 9, 10] -> "1-3, 7, 9-10" (for status messages)."""
    parts: list[str] = []
    nums = sorted(set(pages))
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ", ".join(parts)


def ocr_note(applied: list[int]) -> str | None:
    """The status_detail sentence recording which pages were OCR'd (CONTRACTS §5)."""
    return f"OCR applied to pages {format_page_list(applied)}." if applied else None
