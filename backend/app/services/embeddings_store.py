"""Store and use dense chunk embeddings (core/dense.py).

* `embed_document` (job `embed_document`, chained after processing when DENSE_EMBEDDER is
  set): embeds the document's chunks that don't have a vector for the current model yet.
  Usage is recorded (task "embed"); text never leaves except to the embeddings provider.
* `dense_scores`: one query embedding, then cosine against the stored vectors of the chunks
  being searched. On Postgres with the pgvector column (`app.tools.pgvector_setup`), the
  nearest chunks come from the database index instead of loading every vector.
"""
from __future__ import annotations

import logging

import numpy as np
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from ..core.dense import DenseProvider, DenseScorer, from_bytes, get_dense_provider, to_bytes
from ..models import Chunk, Document, UsageEvent
from ..models_embeddings import ChunkEmbedding

log = logging.getLogger("mindmesh.embeddings")

BATCH = 128
PG_CANDIDATES = 50
_pgvector_ready: dict[str, bool] = {}


def embed_document(document_id: str, provider: DenseProvider | None = None) -> int:
    """Job body. Returns how many chunks were embedded."""
    from ..db import SessionLocal

    provider = provider or get_dense_provider()
    if provider is None:
        return 0
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return 0
        done = set(db.scalars(select(ChunkEmbedding.chunk_id).where(
            ChunkEmbedding.document_id == doc.id, ChunkEmbedding.model == provider.name)))
        todo = [c for c in db.scalars(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.ordinal))
                if c.id not in done]
        n = 0
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            vecs = provider.embed([f"{c.section}\n{c.text}".strip() for c in batch], "document")
            for c, v in zip(batch, vecs):
                db.add(ChunkEmbedding(chunk_id=c.id, owner_id=doc.owner_id, document_id=doc.id, model=provider.name,
                                      dim=int(v.shape[0]), vector=to_bytes(v)))
            tokens = int(getattr(provider, "last_tokens", 0) or 0)
            db.add(UsageEvent(owner_id=doc.owner_id, task="embed", model=provider.name, input_tokens=tokens,
                              output_tokens=0, latency_ms=0, prompt_version="dense"))
            db.commit()
            n += len(batch)
        if n and _has_pgvector(db):
            _sync_pgvector(db, doc.id, provider.name)
        log.info("embedded %d chunks of document %s with %s", n, doc.id, provider.name)
        return n
    finally:
        db.close()


def dense_scores(db: Session, owner_id: str, chunk_ids: list[str], query: str,
                 provider: DenseProvider | None = None) -> dict[str, float] | None:
    """{chunk id: cosine} for the query, or None when dense retrieval is off or nothing is embedded."""
    provider = provider or get_dense_provider()
    if provider is None or not chunk_ids:
        return None
    q = provider.embed([query], "query")[0]
    if _has_pgvector(db):
        return _pg_nearest(db, owner_id, chunk_ids, provider.name, q)
    rows = db.execute(select(ChunkEmbedding.chunk_id, ChunkEmbedding.vector, ChunkEmbedding.dim).where(
        ChunkEmbedding.owner_id == owner_id, ChunkEmbedding.model == provider.name,
        ChunkEmbedding.chunk_id.in_(chunk_ids))).all()
    if not rows:
        return None
    scorer = DenseScorer([r[0] for r in rows], np.stack([from_bytes(r[1], r[2]) for r in rows]), q)
    return scorer.scores()


# ---------------------------------------------------------------- pgvector (optional)

def _has_pgvector(db: Session) -> bool:
    bind = db.get_bind()
    key = str(bind.url)
    if key not in _pgvector_ready:
        ok = False
        if bind.dialect.name == "postgresql":
            try:
                ok = any(c["name"] == "embedding_vec" for c in inspect(bind).get_columns("chunk_embeddings"))
            except Exception:  # noqa: BLE001
                ok = False
        _pgvector_ready[key] = ok
    return _pgvector_ready[key]


def _vec_literal(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v.tolist()) + "]"


def _sync_pgvector(db: Session, document_id: str, model: str) -> None:
    db.execute(text("UPDATE chunk_embeddings SET embedding_vec = CAST(:v AS vector) WHERE id = :id"),
               [{"v": _vec_literal(from_bytes(r.vector, r.dim)), "id": r.id} for r in db.scalars(
                   select(ChunkEmbedding).where(ChunkEmbedding.document_id == document_id, ChunkEmbedding.model == model))])
    db.commit()


def _pg_nearest(db: Session, owner_id: str, chunk_ids: list[str], model: str, q: np.ndarray) -> dict[str, float] | None:
    rows = db.execute(text(
        "SELECT chunk_id, 1 - (embedding_vec <=> CAST(:q AS vector)) AS cos FROM chunk_embeddings "
        "WHERE owner_id = :o AND model = :m AND chunk_id = ANY(:ids) AND embedding_vec IS NOT NULL "
        "ORDER BY embedding_vec <=> CAST(:q AS vector) LIMIT :lim"),
        {"q": _vec_literal(q), "o": owner_id, "m": model, "ids": list(chunk_ids), "lim": PG_CANDIDATES}).all()
    return {r[0]: float(r[1]) for r in rows} or None
