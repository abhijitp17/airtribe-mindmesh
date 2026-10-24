"""Dense (learned) embeddings: providers, storage, the job, retrieval fusion, safety of the gate."""
import dataclasses
import json
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_dense.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import httpx  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core import dense as dn  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Chunk, UsageEvent  # noqa: E402
from app.models_embeddings import ChunkEmbedding  # noqa: E402
from app.services import embeddings_store as store  # noqa: E402
from app.services.learning import ChunkData, retrieve  # noqa: E402


# ---------------------------------------------------------------- providers

def test_fake_provider_is_normalised_and_folds_synonyms():
    p = dn.FakeDenseProvider()
    v = p.embed(["How long do jobs wait?", "Queue time in a factory", "Revenue recognition rules"])
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0)
    assert v[0] @ v[1] > v[0] @ v[2]


def test_voyage_provider_batches_orders_and_retries():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.headers["authorization"] == "Bearer k" and body["input_type"] == "query"
        if len(calls) == 1:
            return httpx.Response(429)
        n = len(body["input"])
        data = [{"index": i, "embedding": [float(i + 1), 0.0, 0.0]} for i in reversed(range(n))]
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 7}})

    p = dn.VoyageProvider("k", "voyage-3.5", 3, client=httpx.Client(transport=httpx.MockTransport(handler)))
    p.BATCH = 2
    v = p.embed(["a", "b", "c"], "query")
    assert v.shape == (3, 3) and np.allclose(v[:, 0], 1.0)  # normalised, in input order
    assert [len(c["input"]) for c in calls] == [2, 2, 1] and calls[1]["output_dimension"] == 3


def test_voyage_needs_a_key(monkeypatch):
    s = dataclasses.replace(get_settings(), dense_embedder="voyage", voyage_api_key=None)
    monkeypatch.setattr("app.config.get_settings", lambda: s)
    assert dn.get_dense_provider() is None
    assert dn.get_dense_provider("off") is None


# ---------------------------------------------------------------- storage and the job

def _on(monkeypatch, threshold=None):
    s = dataclasses.replace(get_settings(), dense_embedder="fake", dense_found_threshold=threshold)
    monkeypatch.setattr("app.config.get_settings", lambda: s)
    for mod in ("app.services.ingestion", "app.services.learning"):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: s)
    return s


def _upload(client, sample_pdf, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    doc = client.post("/api/documents?rights_confirmed=true", headers=h,
                      files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()["id"]
    return h, r.json()["user"]["id"], doc


def test_processing_embeds_every_chunk_once(client, sample_pdf, monkeypatch):
    _on(monkeypatch)
    h, me, doc = _upload(client, sample_pdf, "d1@example.com")
    with SessionLocal() as db:
        chunks = db.scalars(select(Chunk.id).where(Chunk.document_id == doc)).all()
        rows = db.scalars(select(ChunkEmbedding).where(ChunkEmbedding.document_id == doc)).all()
        assert sorted(r.chunk_id for r in rows) == sorted(chunks)
        assert all(r.owner_id == me and r.model == "fake:stems-v1" and r.dim == 128 for r in rows)
        assert db.scalar(select(UsageEvent).where(UsageEvent.task == "embed", UsageEvent.owner_id == me))
    assert store.embed_document(doc) == 0, "idempotent: nothing left to embed"
    # Deleting the document removes its vectors (cascade).
    assert client.delete(f"/api/documents/{doc}", headers=h).status_code == 204
    with SessionLocal() as db:
        assert db.scalars(select(ChunkEmbedding).where(ChunkEmbedding.document_id == doc)).all() == []


def test_dense_scores_are_owner_scoped(client, sample_pdf, monkeypatch):
    _on(monkeypatch)
    _h, me, doc = _upload(client, sample_pdf, "d2@example.com")
    _h2, other, _ = _upload(client, sample_pdf, "d3@example.com")
    with SessionLocal() as db:
        ids = list(db.scalars(select(Chunk.id).where(Chunk.document_id == doc)))
        mine = store.dense_scores(db, me, ids, "What is Little's Law?")
        assert set(mine) == set(ids) and all(-1.0 <= v <= 1.0 for v in mine.values())
        assert store.dense_scores(db, other, ids, "What is Little's Law?") is None


def test_tutor_still_answers_with_dense_on_and_survives_a_provider_failure(client, sample_pdf, monkeypatch):
    _on(monkeypatch)
    h, _me, doc = _upload(client, sample_pdf, "d4@example.com")
    r = client.post("/api/tutor/ask", headers=h, json={"question": "What is Little's Law?", "document_ids": [doc]})
    assert r.json()["status"] == "verified"

    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(store, "dense_scores", boom)
    r = client.post("/api/tutor/ask", headers=h, json={"question": "What is Little's Law?", "document_ids": [doc]})
    assert r.json()["status"] == "verified"


# ---------------------------------------------------------------- retrieval: re-rank, never flip coverage

CH = [ChunkData(f"c{i}", t, i + 1, i + 1, s) for i, (s, t) in enumerate([
    ("Queues", "Queue time is how long a job waits before a station starts on it."),
    ("Throughput", "Throughput is the rate at which finished jobs leave the line."),
    ("Capacity", "Capacity is the most a station can produce per hour."),
])]


def _dense_for(query):
    p = dn.FakeDenseProvider()
    return dn.DenseScorer([c.id for c in CH], p.embed([c.text for c in CH]), p.embed([query])[0]).scores()


def test_dense_reranks_but_does_not_decide_coverage_without_a_threshold(monkeypatch):
    _on(monkeypatch, threshold=None)
    off_topic = "Who won the cup final?"
    assert retrieve(CH, off_topic) == []
    assert retrieve(CH, off_topic, dense={"c0": 0.99, "c1": 0.98, "c2": 0.97}) == [], "uncalibrated dense can't admit it"
    q = "How long do jobs wait?"
    assert retrieve(CH, q, dense=_dense_for(q))[0].chunk_id == "c0"


def test_a_calibrated_threshold_lets_dense_admit_a_paraphrase(monkeypatch):
    q = "Wie lange wartet ein Auftrag?"  # no shared words: only a (multilingual) embedding links it
    _on(monkeypatch, threshold=None)
    assert retrieve(CH, q, dense={"c0": 0.9, "c1": 0.1, "c2": 0.1}) == []
    _on(monkeypatch, threshold=0.8)
    assert retrieve(CH, q, dense={"c0": 0.9, "c1": 0.1, "c2": 0.1})[0].chunk_id == "c0"


def test_calibration_recommends_a_threshold_above_every_off_topic_question():
    from evals.calibrate_dense import recommend

    rows = [("a", "answer", 0.7), ("b", "answer", 0.5), ("c", "not_found", 0.55), ("d", "not_found", 0.3)]
    t, share = recommend(rows)
    assert t == pytest.approx(0.57) and share == 0.5
