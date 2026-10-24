"""The knowledge map (P4): the learner's own concept graph, ready to draw.

A read-only view of what P1-P3 built, nothing new is inferred here:
  * nodes      concepts (merged ones are already folded into their survivor), each with its
               mastery level (knowledge tracing), the documents that cover it with page and quote
               (so every node traces back to a source), and the taxonomy skill it maps to.
  * edges      "A is a prerequisite of B" between shown concepts; `verified` when grounded in a
               page quote (unverified planner edges are drawn dashed).
Capped at `limit` concepts, best connected first, so a large library stays fast and legible;
`total_concepts` says how many exist.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document
from ..models_kg import KgEdge, KgNode
from .concepts import COVERS
from .knowledge_graph import PREREQUISITE_OF, canonical_key
from .taxonomy import IN_TAXONOMY

DEFAULT_LIMIT = 150
MAX_LIMIT = 400
SOURCES_PER_NODE = 3


def knowledge_map(db: Session, owner_id: str, limit: int = DEFAULT_LIMIT) -> dict:
    from .engagement import mastery

    concepts = {n.id: n for n in db.scalars(select(KgNode).where(
        KgNode.owner_id == owner_id, KgNode.kind == "concept", KgNode.merged_into_id.is_(None)))}
    empty = {"nodes": [], "edges": [], "documents": [], "total_concepts": len(concepts)}
    if not concepts:
        return empty
    edges = db.scalars(select(KgEdge).where(KgEdge.owner_id == owner_id,
                                            KgEdge.rel.in_((PREREQUISITE_OF, COVERS, IN_TAXONOMY)))).all()
    other_ids = {e.src_id for e in edges if e.rel == COVERS} | {e.dst_id for e in edges if e.rel == IN_TAXONOMY}
    others = {n.id: n for n in db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.id.in_(other_ids)))}
    # Document nodes are keyed by document id; only documents that still exist are shown.
    doc_keys = {n.canonical_key for n in others.values() if n.kind == "document"}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.owner_id == owner_id, Document.id.in_(doc_keys)))}

    sources: dict[str, list[dict]] = defaultdict(list)
    skill: dict[str, str] = {}
    prereq = []
    for e in edges:
        if e.rel == PREREQUISITE_OF and e.src_id in concepts and e.dst_id in concepts:
            prereq.append(e)
        elif e.rel == COVERS and e.dst_id in concepts:
            src = others.get(e.src_id)
            if src is not None and src.canonical_key in docs:
                p = e.provenance or {}
                sources[e.dst_id].append({"document_id": src.canonical_key, "page": p.get("page"),
                                          "quote": str(p.get("quote") or "")[:240]})
        elif e.rel == IN_TAXONOMY and e.src_id in concepts and e.dst_id in others:
            skill[e.src_id] = others[e.dst_id].name

    degree: dict[str, int] = defaultdict(int)
    for e in prereq:
        degree[e.src_id] += 1
        degree[e.dst_id] += 1
    levels = {canonical_key(name): m for name, m in mastery(owner_id, db).items()}

    def rank(nid: str) -> tuple:
        n = concepts[nid]
        return (-(2 * degree[nid] + len(sources[nid]) + (canonical_key(n.name) in levels)), n.name.casefold())

    shown = sorted(concepts, key=rank)[:max(1, min(limit, MAX_LIMIT))]
    keep = set(shown)
    nodes = []
    for nid in shown:
        n = concepts[nid]
        m = levels.get(canonical_key(n.name))
        nodes.append({"id": nid, "name": n.name, "level": m.level if m else "unverified",
                      "evidence": m.evidence_count if m else 0, "due_for_review": bool(m and m.due_for_review),
                      "skill": skill.get(nid), "sources": sources[nid][:SOURCES_PER_NODE],
                      "source_count": len(sources[nid]), "degree": degree[nid]})
    used_docs = {s["document_id"] for n in nodes for s in n["sources"]}
    return {
        "nodes": nodes,
        "edges": [{"source": e.src_id, "target": e.dst_id, "verified": bool(e.verified)}
                  for e in prereq if e.src_id in keep and e.dst_id in keep],
        "documents": [{"id": d.id, "title": d.title or d.filename} for d in docs.values() if d.id in used_docs],
        "total_concepts": len(concepts),
    }
