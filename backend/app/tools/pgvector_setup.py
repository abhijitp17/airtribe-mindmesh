"""Enable database-side nearest-neighbour search for dense embeddings (Postgres + pgvector).

    python -m app.tools.pgvector_setup [--dim 1024]

Run once, as a role allowed to create extensions (the migrate/admin role, not the app role).
Adds `chunk_embeddings.embedding_vec vector(dim)` with an HNSW cosine index and backfills it
from the stored float32 vectors. Without it, retrieval computes cosines in memory, which is fine
for per-user corpora of a few thousand chunks. Idempotent.
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from ..jobs import system_context


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Set up pgvector for chunk embeddings")
    p.add_argument("--dim", type=int, default=None, help="vector dimension (default: DENSE_DIM)")
    args = p.parse_args(argv)
    from ..config import get_settings
    from ..db import SessionLocal
    from ..services.embeddings_store import _sync_pgvector, _pgvector_ready

    dim = args.dim or get_settings().dense_dim
    with system_context(), SessionLocal() as db:
        if db.get_bind().dialect.name != "postgresql":
            print("not Postgres: nothing to do (in-memory search is used)")
            return 0
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.execute(text(f"ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS embedding_vec vector({int(dim)})"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_vec ON chunk_embeddings "
                        "USING hnsw (embedding_vec vector_cosine_ops)"))
        db.commit()
        _pgvector_ready.clear()
        docs = db.execute(text("SELECT DISTINCT document_id, model FROM chunk_embeddings WHERE dim = :d "
                               "AND embedding_vec IS NULL"), {"d": dim}).all()
        for doc_id, model in docs:
            _sync_pgvector(db, doc_id, model)
    print(f"pgvector ready: vector({dim}), HNSW cosine index; backfilled {len(docs)} document(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
