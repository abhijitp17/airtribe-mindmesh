from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.doc_formats import MEDIA_TYPES, detect
from ..core.upload_safety import UploadRejected, content_disposition, scan
from ..db import get_db
from ..deps import current_user
from ..models import Chunk, Document, User
from ..schemas import ChunkOut, ConceptOut, DocumentOut, DocumentRename
from ..jobs import dispatch
from ..services import concepts as concepts_svc
from ..storage import get_storage
from ..services import analytics

router = APIRouter(prefix="/documents", tags=["documents"])


def owned_document(doc_id: str, user: User, db: Session) -> Document:
    """The single place document ownership is enforced (FR-015).

    A document that exists but belongs to someone else returns 404, not 403,
    so ids cannot be probed.
    """
    doc = db.scalar(select(Document).where(Document.id == doc_id, Document.owner_id == user.id))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.post("", response_model=DocumentOut, status_code=201)
async def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    rights_confirmed: bool = Query(False, description="User confirms they may use this file for personal study"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not rights_confirmed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please confirm you have the right to use this file for personal study.")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File exceeds {get_settings().max_upload_mb} MB limit.")
    if detect(data, file.filename) is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "Upload a PDF, Word (.docx), text, Markdown or HTML file.")
    try:
        await run_in_threadpool(scan, data)  # no-op unless UPLOAD_SCAN is configured
    except UploadRejected as exc:
        raise HTTPException(exc.status, exc.message) from exc

    return _create(db, user, data, file.filename or "document.pdf", background)


SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample-notebook.md"


@router.post("/sample", response_model=DocumentOut, status_code=201)
def add_sample(background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """First run (P4): add a short sample chapter written for Mindmesh, so the map, quizzes and
    notes-first answers can be tried before uploading anything. Idempotent; deletable like any document."""
    return _create(db, user, SAMPLE.read_bytes(), "how-learning-sticks.md", background, title="How Learning Sticks (sample)")


def _create(db: Session, user: User, data: bytes, filename: str, background: BackgroundTasks, title: str | None = None) -> Document:
    checksum = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Document).where(Document.owner_id == user.id, Document.checksum == checksum))
    if existing:
        return existing  # idempotent re-upload

    storage = get_storage()
    key = storage.new_key(user.id)
    storage.put(key, data)
    name = filename.replace("/", "_").replace("\\", "_")[:255]
    doc = Document(
        owner_id=user.id, filename=name, title=(title or name.rsplit(".", 1)[0])[:255],
        storage_key=key, checksum=checksum, size_bytes=len(data), status="uploaded",
    )
    db.add(doc)
    db.commit()
    dispatch("ingest_document", {"document_id": doc.id}, background, db=db)
    analytics.record(db, user, "document_uploaded")
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Document).where(Document.owner_id == user.id).order_by(Document.created_at.desc())).all()


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owned_document(doc_id, user, db)


@router.patch("/{doc_id}", response_model=DocumentOut)
def rename(doc_id: str, body: DocumentRename, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned_document(doc_id, user, db)
    doc.title = body.title.strip()
    db.commit()
    return doc


@router.post("/{doc_id}/retry", response_model=DocumentOut)
def retry(doc_id: str, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned_document(doc_id, user, db)
    if doc.status == "processing":
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is already processing.")
    doc.status, doc.status_detail, doc.pages_done = "uploaded", None, None
    db.commit()
    dispatch("ingest_document", {"document_id": doc.id}, background, db=db)
    return doc


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned_document(doc_id, user, db)
    get_storage().delete(doc.storage_key)
    concepts_svc.remove_document(db, user.id, doc.id)  # its "covers" edges; shared concept nodes stay
    db.delete(doc)  # chunks cascade
    db.commit()


@router.get("/{doc_id}/concepts", response_model=list[ConceptOut])
def list_concepts(doc_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Concepts the document teaches (from the extraction job), each with the quote that grounds it.
    Empty until the job has run, or when extraction is off."""
    doc = owned_document(doc_id, user, db)
    return concepts_svc.document_concepts(db, user.id, doc.id)


@router.get("/{doc_id}/chunks", response_model=list[ChunkOut])
def list_chunks(
    doc_id: str,
    page: int | None = Query(None, ge=1),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    doc = owned_document(doc_id, user, db)
    q = select(Chunk).where(Chunk.document_id == doc.id, Chunk.owner_id == user.id)
    if page is not None:
        q = q.where(Chunk.page_start <= page, Chunk.page_end >= page)
    return db.scalars(q.order_by(Chunk.ordinal)).all()


@router.get("/{doc_id}/file")
def download(doc_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned_document(doc_id, user, db)
    data = get_storage().get(doc.storage_key)
    return Response(
        data,
        media_type=MEDIA_TYPES.get(detect(data, doc.filename) or "", "application/octet-stream"),
        headers={"Content-Disposition": content_disposition(doc.filename), "Cache-Control": "private, no-store"},
    )
