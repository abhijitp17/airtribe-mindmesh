"""Filling the processing wait: first pages saved early, progress, stable chunk ids, partial use."""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_processing_wait.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Chunk, Document  # noqa: E402
from app.services import ingestion  # noqa: E402
from tests.conftest import make_pdf  # noqa: E402

TOPICS = ["Variability", "Queueing", "Inventory", "Capacity", "Batching", "Kanban"]


def long_pdf(n_pages: int) -> bytes:
    pages = []
    for i in range(1, n_pages + 1):
        topic = TOPICS[(i - 1) // 5 % len(TOPICS)]
        lines = [f"Chapter {i} {topic} in practice"] if i % 5 == 1 else []
        lines += [f"Page {i}: {topic} affects cycle time, throughput and work in process in a production line."] * 9
        pages.append(lines)
    return make_pdf(pages)


def _signup(client, email="wait@example.com"):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _upload(client, h, pdf, name="long.pdf"):
    r = client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": (name, pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_long_document_saves_first_pages_early_and_keeps_their_ids(client, monkeypatch):
    h = _signup(client)
    seen: dict = {}
    real_progress = ingestion._progress

    def spying_progress(db, doc):
        inner = real_progress(db, doc)

        def on_page(pages, page_count):
            inner(pages, page_count)
            if len(pages) == ingestion.EARLY_PAGES:  # right after the early save, look from another session
                with SessionLocal() as other:
                    d = other.get(Document, doc.id)
                    rows = other.scalars(select(Chunk).where(Chunk.document_id == doc.id)).all()
                    seen.update(status=d.status, pages_done=d.pages_done, page_count=d.page_count,
                                started=d.processing_started_at, ids={c.id for c in rows},
                                max_page=max(c.page_end for c in rows))
            if len(pages) == 30:
                with SessionLocal() as other:
                    seen["pages_done_30"] = other.get(Document, doc.id).pages_done
        return on_page

    monkeypatch.setattr(ingestion, "_progress", spying_progress)
    doc_id = _upload(client, h, long_pdf(40))

    assert seen["status"] == "processing"
    assert seen["pages_done"] == ingestion.EARLY_PAGES and seen["page_count"] == 40
    assert seen["started"] is not None
    assert seen["ids"] and seen["max_page"] <= ingestion.EARLY_PAGES
    assert seen["pages_done_30"] == 30

    d = client.get(f"/api/documents/{doc_id}", headers=h).json()
    assert d["status"] == "ready" and d["pages_done"] == 40 and d["page_count"] == 40
    with SessionLocal() as db:
        final = {c.id for c in db.scalars(select(Chunk).where(Chunk.document_id == doc_id))}
        pages = sorted({c.page_end for c in db.scalars(select(Chunk).where(Chunk.document_id == doc_id))})
    assert seen["ids"] <= final, "early chunks were replaced: citations made during the wait would break"
    assert pages[-1] == 40


def test_short_document_has_no_early_phase(client, sample_pdf, monkeypatch):
    h = _signup(client)
    saves = []
    monkeypatch.setattr(ingestion, "_sync_chunks", lambda db, doc, chunks, real=ingestion._sync_chunks: (saves.append(len(chunks)), real(db, doc, chunks))[1])
    doc_id = _upload(client, h, sample_pdf, "short.pdf")
    assert len(saves) == 1
    d = client.get(f"/api/documents/{doc_id}", headers=h).json()
    assert d["status"] == "ready" and d["pages_done"] == d["page_count"]


def test_partly_read_document_can_be_used_but_not_before_first_pages(client):
    h = _signup(client)
    doc_id = _upload(client, h, long_pdf(20))
    with SessionLocal() as db:
        d = db.get(Document, doc_id)
        d.status, d.pages_done = "processing", ingestion.EARLY_PAGES
        db.commit()

    r = client.post("/api/tutor/ask", headers=h, json={"question": "What affects cycle time?", "document_ids": [doc_id]})
    assert r.status_code == 200, r.text
    r = client.post("/api/quizzes", headers=h, json={"document_ids": [doc_id], "count": 3})
    assert r.status_code in (200, 201), r.text

    with SessionLocal() as db:
        db.get(Document, doc_id).pages_done = None
        db.commit()
    r = client.post("/api/tutor/ask", headers=h, json={"question": "What affects cycle time?", "document_ids": [doc_id]})
    assert r.status_code == 409


def test_failure_after_early_save_leaves_document_unusable(client, monkeypatch):
    h = _signup(client)
    real_chunk_pages = ingestion.chunk_pages
    calls = {"n": 0}

    def flaky(pages):
        calls["n"] += 1
        if calls["n"] > 1:  # the early save works, the final pass crashes
            raise RuntimeError("boom")
        return real_chunk_pages(pages)

    monkeypatch.setattr(ingestion, "chunk_pages", flaky)
    doc_id = _upload(client, h, long_pdf(30))
    d = client.get(f"/api/documents/{doc_id}", headers=h).json()
    assert d["status"] == "failed" and d["pages_done"] is None
    r = client.post("/api/tutor/ask", headers=h, json={"question": "What affects cycle time?", "document_ids": [doc_id]})
    assert r.status_code == 409


@pytest.mark.parametrize("n", [ingestion.EARLY_PAGES, ingestion.EARLY_PAGES + 1])
def test_boundary_sizes(client, n):
    h = _signup(client, f"b{n}@example.com")
    doc_id = _upload(client, h, long_pdf(n))
    d = client.get(f"/api/documents/{doc_id}", headers=h).json()
    assert d["status"] == "ready" and d["pages_done"] == n
