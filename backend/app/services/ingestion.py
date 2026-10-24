"""Document ingestion job: extract -> chunk -> persist, with status lifecycle.

Runs as a background task in the MVP. It is idempotent (re-running replaces
the document's chunks) so it can move to a real job queue (Redis/SQS worker)
without changes. A failed job never deletes the uploaded file (PRD 11.5).

Filling the wait (ux-research "Fill the processing wait"): on a long document the
first EARLY_PAGES are chunked and saved straight away, so the learner can ask, read
and take a short quiz on them while the rest is read. ``pages_done`` reports progress.
The final pass keeps every early chunk whose content didn't change, so citations made
during the wait still point at the same rows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.chunking import Chunk as ChunkSpec, chunk_pages
from ..core.doc_formats import detect, extract_text_document
from ..core.ocr import ocr_pages
from ..core.pdf_extract import PageText, PdfExtractionError, apply_ocr, extract_pdf, ocr_note
from ..db import SessionLocal
from ..models import Chunk, Document
from ..storage import get_storage

log = logging.getLogger("mindmesh.ingestion")
PROCESSING_VERSION = "1"
EARLY_PAGES = 12  # saved and usable first on longer documents
PROGRESS_EVERY = 10  # pages between progress writes


def _sync_chunks(db: Session, doc: Document, chunks: list[ChunkSpec]) -> None:
    """Make the stored chunks equal ``chunks``, keeping rows whose content is unchanged (stable ids)."""
    existing = {c.ordinal: c for c in db.scalars(select(Chunk).where(Chunk.document_id == doc.id))}
    wanted = {c.ordinal: c for c in chunks}
    for ordinal, row in existing.items():
        new = wanted.get(ordinal)
        if new is None or (row.page_start, row.page_end, row.section, row.text) != (
                new.page_start, new.page_end, new.section_label, new.text):
            db.delete(row)
        else:
            wanted.pop(ordinal)
    db.flush()
    db.add_all(
        Chunk(
            document_id=doc.id, owner_id=doc.owner_id, ordinal=c.ordinal,
            page_start=c.page_start, page_end=c.page_end, section=c.section_label, text=c.text,
        )
        for c in wanted.values()
    )


def _progress(db: Session, doc: Document):
    """on_page callback: save the first pages early, then record progress every few pages."""
    def on_page(pages: list[PageText], page_count: int) -> None:
        n = len(pages)
        if n == EARLY_PAGES and page_count > EARLY_PAGES:
            early = chunk_pages([p for p in pages if not p.low_text])
            if early:
                _sync_chunks(db, doc, early[:-1] or early)  # the last early chunk may still grow onto the next page
                doc.pages_done, doc.page_count = n, page_count
                db.commit()
        elif n % PROGRESS_EVERY == 0 and n < page_count and doc.pages_done is not None:
            doc.pages_done = n
            db.commit()
    return on_page


def process_document(document_id: str) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        doc.status, doc.status_detail = "processing", None
        doc.pages_done, doc.processing_started_at = None, datetime.now(timezone.utc)
        db.commit()
        try:
            data = get_storage().get(doc.storage_key)
            fmt = detect(data, doc.filename)
            ocr_applied: list[int] = []
            if fmt is None:
                raise PdfExtractionError("This file type isn't supported.")
            if fmt != "pdf":  # Word, HTML, Markdown, text (core.doc_formats): no OCR, no layout pass
                result = extract_text_document(data, fmt, max_pages=get_settings().max_pages)
            else:
                result = extract_pdf(data, max_pages=get_settings().max_pages, on_page=_progress(db, doc))
            if fmt == "pdf" and result.low_text_pages:
                # No-op unless OCR is enabled. Never raises (see core.ocr).
                # Idempotent: it always starts from the stored original bytes.
                result, ocr_applied = apply_ocr(result, ocr_pages(data, result.low_text_pages))
            chunks = chunk_pages(result.pages)
        except PdfExtractionError as exc:
            _fail(db, doc, str(exc))
            return
        except Exception:  # noqa: BLE001
            log.exception("ingestion crashed for document %s", document_id)
            _fail(db, doc, "Unexpected processing error. You can retry.")
            return

        _sync_chunks(db, doc, chunks)
        doc.page_count = result.page_count
        doc.pages_done = result.page_count
        doc.title = doc.title or result.title
        doc.low_text_pages = result.low_text_pages
        doc.processing_version = PROCESSING_VERSION
        note = ocr_note(ocr_applied)
        if not chunks:
            doc.status = "needs_attention"
            doc.status_detail = (
                "No readable text was found, even after OCR."
                if get_settings().ocr != "off"
                else "No readable text was found. The file may be a scanned image; OCR is not enabled."
            )
        elif result.needs_attention:
            doc.status = "needs_attention"
            doc.status_detail = " ".join(filter(None, [note, *result.warnings]))
        else:
            doc.status = "ready"
            doc.status_detail = " ".join(filter(None, [note, *result.warnings])) or None
        db.commit()
        log.info(
            "processed document %s pages=%d chunks=%d ocr_pages=%d status=%s",
            doc.id, result.page_count, len(chunks), len(ocr_applied), doc.status,
        )
        if chunks and get_settings().dense_embedder != "off":
            from ..jobs import chain

            chain("embed_document", {"document_id": doc.id})
        if chunks and get_settings().concept_extraction:
            from ..jobs import chain

            chain("extract_concepts", {"document_id": doc.id})
    finally:
        db.close()


def _fail(db: Session, doc: Document, detail: str) -> None:
    db.rollback()  # a failed document can't be used (learning checks status), so early chunks are harmless
    doc.status, doc.status_detail, doc.pages_done = "failed", detail, None
    db.commit()
