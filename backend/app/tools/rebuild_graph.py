"""Rebuild knowledge graphs: merge concepts, derive edges and competency links.

    python -m app.tools.rebuild_graph [--user USER_ID] [--reextract]

--reextract also re-runs concept extraction (one fast-model call per document, charged to
each owner's budget), e.g. so documents processed before P2 get grounded prerequisites.
Prints counts only.
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from ..jobs import system_context


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rebuild knowledge graphs")
    p.add_argument("--user", help="only this user id")
    p.add_argument("--reextract", action="store_true", help="re-run concept extraction for each ready document")
    args = p.parse_args(argv)
    from ..db import SessionLocal
    from ..models import Document, User
    from ..services.concepts import extract_for_document
    from ..services.graph import rebuild_graph

    with system_context():
        with SessionLocal() as db:
            users = [args.user] if args.user else list(db.scalars(select(User.id)))
            docs = list(db.execute(select(Document.id, Document.owner_id).where(
                Document.status.in_(("ready", "needs_attention")))))
        extracted = 0
        if args.reextract:
            for doc_id, owner in docs:
                if owner in users:
                    extracted += extract_for_document(doc_id)
        totals: dict[str, int] = {}
        for uid in users:
            for k, v in rebuild_graph(uid).items():
                totals[k] = totals.get(k, 0) + v
    print(f"users: {len(users)}; concepts re-extracted: {extracted}; " + ", ".join(f"{k}: {v}" for k, v in sorted(totals.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
