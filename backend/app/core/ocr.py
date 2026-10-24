"""OCR fallback for pages without a usable text layer (CONTRACTS §5, FR-013).

``ocr_pages(pdf_bytes, page_numbers) -> {page_number: text}`` is best-effort
by design. It never raises. A missing engine, a broken page, a renderer error
or an exhausted time budget each mean "no OCR text for that page", and
ingestion keeps the text-layer result. That's why it's safe to call
unconditionally on every ``low_text`` page.

Engines (``settings.ocr``):

* ``off`` (default): no-op, returns {}.
* ``tesseract``: renders each page with pypdfium2 at ``RENDER_DPI`` and runs
  ``pytesseract``. That needs the ``pytesseract`` Python package plus the
  ``tesseract-ocr`` system binary (Debian: ``apt-get install tesseract-ocr``).
  If either is missing, it logs once and returns {}.
* ``vision``: reserved in config for a multimodal-model fallback. It isn't
  implemented, so it logs once and returns {}, the same as an unavailable engine.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterable

log = logging.getLogger("mindmesh.ocr")

# 200 dpi is a common trade-off for Tesseract on body text: accuracy drops
# below ~150 dpi, and above ~300 dpi the gain is small while time and memory grow
# quadratically. A Letter page at 200 dpi is 1700x2200 px, ~11 MB as RGB.
RENDER_DPI = 200
_PDF_POINTS_PER_INCH = 72  # PDF user-space unit. pypdfium2's ``scale`` is dpi / 72.

# Upper bounds per document, so that one 900-page scanned book can't hold an
# ingestion worker for an hour. Tesseract takes ~1-3 s per page at 200 dpi on
# one core, so 50 pages fits in the 120 s budget on typical hardware. Pages
# beyond the cap stay flagged as low_text, and the user is told (FR-013).
MAX_OCR_PAGES_PER_DOC = 50
OCR_TIME_BUDGET_S = 120.0

# Tesseract language(s). English matches the current product scope.
TESSERACT_LANG = "eng"

_warned: set[str] = set()


def _warn_once(key: str, msg: str, *args: object) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning(msg, *args)


# An engine turns one rendered page (a PIL image) into text.
PageOCR = Callable[[object], str]


def _tesseract_engine() -> PageOCR | None:
    try:
        import pytesseract  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - ImportError, or a broken install
        _warn_once("no-pytesseract", "OCR=tesseract but pytesseract is not installed; OCR disabled")
        return None
    try:
        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001 - binary missing from PATH
        _warn_once("no-binary", "OCR=tesseract but the tesseract binary was not found; OCR disabled")
        return None

    def run(image: object) -> str:
        return str(pytesseract.image_to_string(image, lang=TESSERACT_LANG))

    return run


def _engine_for(kind: str) -> PageOCR | None:
    kind = (kind or "off").strip().lower()
    if kind == "off":
        return None
    if kind == "tesseract":
        return _tesseract_engine()
    _warn_once(f"engine-{kind}", "OCR engine %r is not available; OCR disabled", kind)
    return None


def ocr_pages(
    pdf_bytes: bytes,
    page_numbers: Iterable[int],
    *,
    engine: str | None = None,
    max_pages: int = MAX_OCR_PAGES_PER_DOC,
    time_budget_s: float = OCR_TIME_BUDGET_S,
) -> dict[int, str]:
    """OCR the given 1-based pages. Returns only pages that produced text.

    ``engine`` defaults to ``settings.ocr``. The keyword arguments exist for
    tests and batch jobs. Never raises.
    """
    try:
        if engine is None:
            from ..config import get_settings

            engine = get_settings().ocr
        run = _engine_for(engine)
        if run is None:
            return {}
        wanted = sorted({int(p) for p in page_numbers if int(p) >= 1})
        if not wanted:
            return {}
        if len(wanted) > max_pages:
            log.info("OCR capped at %d of %d low-text pages", max_pages, len(wanted))
            wanted = wanted[:max_pages]
        return _run_pages(pdf_bytes, wanted, run, time_budget_s)
    except Exception:  # noqa: BLE001 - OCR is optional and must never break ingestion
        log.exception("OCR failed; continuing without it")
        return {}


def _run_pages(pdf_bytes: bytes, pages: list[int], run: PageOCR, time_budget_s: float) -> dict[int, str]:
    import pypdfium2 as pdfium

    out: dict[int, str] = {}
    deadline = time.monotonic() + time_budget_s
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        n = len(pdf)
        for page_no in pages:
            if page_no > n:
                continue
            if time.monotonic() >= deadline:
                log.info("OCR time budget (%.0fs) exhausted before page %d", time_budget_s, page_no)
                break
            try:
                page = pdf[page_no - 1]
                try:
                    bitmap = page.render(scale=RENDER_DPI / _PDF_POINTS_PER_INCH)
                    image = bitmap.to_pil()
                finally:
                    page.close()
                text = run(image).replace("\x00", "")
            except Exception:  # noqa: BLE001 - one bad page must not stop the rest
                log.warning("OCR failed on page %d", page_no, exc_info=True)
                continue
            if text.strip():
                out[page_no] = text
    finally:
        pdf.close()
    return out
