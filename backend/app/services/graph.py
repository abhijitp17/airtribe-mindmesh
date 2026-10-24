"""Knowledge graph maintenance (P2): concept merging and the per-user rebuild job.

Edge kinds (kg_edges.rel):
  prerequisite_of  src must be learned before dst (planner: unverified; documents: grounded, verified)
  covers           document node -> concept it teaches (concept extraction, grounded)
  same_as          merged concept -> the concept it was merged into (audit trail)
  maps_to          competency (interview skill) node -> concept in the learner's material

Merging moves every edge of the merged node onto the kept node (dropping duplicates and
self-loops), sets `merged_into_id`, and records a same_as edge with the reason. Nothing is
deleted, so a merge can be audited, and attempts stay attached to their original concept
name; `concept_aliases` lets mastery, sessions and retrieval treat the names as one.

`rebuild_graph(owner_id)` is idempotent and runs as the `rebuild_graph` job after concept
extraction and quiz creation (debounced by being cheap when nothing changed).
"""
from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..ai.gateway import BudgetExceeded, Gateway, ModelError, Request
from ..ai.prompts import MERGE_SYSTEM, merge_user
from ..core.concept_merge import pick_canonical, rule_pairs, similar_pairs
from ..models_kg import KgEdge, KgNode
from .knowledge_graph import canonical_key

log = logging.getLogger("mindmesh.graph")

SAME_AS = "same_as"
MAX_MODEL_PAIRS = 30


# ---------------------------------------------------------------- merging

def merge(db: Session, owner_id: str, keep: KgNode, away: KgNode, reason: str, source: str) -> bool:
    """Merge `away` into `keep`. Returns False if there was nothing to do."""
    if keep.id == away.id or away.merged_into_id or keep.owner_id != owner_id or away.owner_id != owner_id:
        return False
    edges = db.scalars(select(KgEdge).where(KgEdge.owner_id == owner_id,
                                            or_(KgEdge.src_id == away.id, KgEdge.dst_id == away.id))).all()
    existing = {(e.src_id, e.dst_id, e.rel) for e in db.scalars(select(KgEdge).where(
        KgEdge.owner_id == owner_id, or_(KgEdge.src_id == keep.id, KgEdge.dst_id == keep.id)))}
    for e in edges:
        if e.rel == SAME_AS:  # earlier merges into `away` now point at `keep`
            e.dst_id = keep.id if e.dst_id == away.id else e.dst_id
            if e.src_id == e.dst_id or (e.src_id, e.dst_id, e.rel) in existing:
                db.delete(e)
            continue
        src = keep.id if e.src_id == away.id else e.src_id
        dst = keep.id if e.dst_id == away.id else e.dst_id
        if src == dst or (src, dst, e.rel) in existing:
            db.delete(e)
            continue
        e.src_id, e.dst_id = src, dst
        existing.add((src, dst, e.rel))
    for n in db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.merged_into_id == away.id)):
        n.merged_into_id = keep.id
    db.flush()
    away.merged_into_id = keep.id
    db.add(KgEdge(owner_id=owner_id, src_id=away.id, dst_id=keep.id, rel=SAME_AS, source=source,
                  verified=source == "rule", provenance={"reason": reason}))
    db.flush()
    return True


def concept_aliases(db: Session, owner_id: str) -> dict[str, str]:
    """{canonical_key(any concept name): display name of the concept it lives in now}."""
    nodes = db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == "concept")).all()
    by_id = {n.id: n for n in nodes}
    out = {}
    for n in nodes:
        cur, hops = n, 0
        while cur.merged_into_id and cur.merged_into_id in by_id and hops < 5:
            cur, hops = by_id[cur.merged_into_id], hops + 1
        out[n.canonical_key] = cur.name
    return out


def canonical_concept(name: str, aliases: dict[str, str]) -> str:
    return aliases.get(canonical_key(name), name)


def _evidence(db: Session, owner_id: str) -> dict[str, int]:
    """How often each concept name is used by questions: the better-used name is kept."""
    from ..models import Question

    return dict(Counter(canonical_key(c) for c in db.scalars(select(Question.concept).where(Question.owner_id == owner_id))))


def _model_confirm(gw: Gateway, pairs, context: list[str]) -> list[bool]:
    numbered = [(i + 1, p.a, p.b) for i, p in enumerate(pairs)]

    def validate(data):
        if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
            raise ValueError("expected {'decisions': [...]}")
        return {int(d["id"]): bool(d.get("same")) for d in data["decisions"] if isinstance(d, dict) and "id" in d}

    req = Request(task="concept_merge", system=MERGE_SYSTEM, user=merge_user(numbered, context), tier="fast",
                  max_tokens=2000, context={"pairs": numbered})
    got = gw.complete_json(req, validate=validate)
    return [got.get(i, False) is True for i, _, _ in numbered]


def merge_concepts(db: Session, owner_id: str, gw: Gateway | None = None) -> dict[str, int]:
    """Apply rule merges, then (with a gateway) model-confirmed merges of similar names."""
    counts = {"rule": 0, "model": 0}
    for _round in range(3):  # merges can expose new pairs (a plural of a merged name)
        nodes = db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == "concept",
                                                KgNode.merged_into_id.is_(None))).all()
        by_key = {n.canonical_key: n for n in nodes}
        names = [n.name for n in nodes]
        evidence = _evidence(db, owner_id)
        changed = 0
        for p in rule_pairs(names):
            keep_name, away_name = pick_canonical(p.a, p.b, evidence)
            keep, away = by_key.get(canonical_key(keep_name)), by_key.get(canonical_key(away_name))
            if keep and away and not keep.merged_into_id and merge(db, owner_id, keep, away, p.reason, "rule"):
                counts["rule"] += 1
                changed += 1
        if not changed:
            break
    if gw is None:
        return counts
    nodes = db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == "concept",
                                            KgNode.merged_into_id.is_(None))).all()
    by_key = {n.canonical_key: n for n in nodes}
    names = [n.name for n in nodes]
    decided = {frozenset((e.src_id, e.dst_id)) for e in db.scalars(select(KgEdge).where(
        KgEdge.owner_id == owner_id, KgEdge.rel == "not_same"))}
    pairs = [p for p in similar_pairs(names, limit=MAX_MODEL_PAIRS)
             if frozenset((by_key[canonical_key(p.a)].id, by_key[canonical_key(p.b)].id)) not in decided]
    if not pairs:
        return counts
    try:
        verdicts = _model_confirm(gw, pairs, names)
    except (BudgetExceeded, ModelError, ValueError) as exc:
        log.info("model merge skipped: %s", type(exc).__name__)
        return counts
    evidence = _evidence(db, owner_id)
    for p, same in zip(pairs, verdicts):
        a, b = by_key.get(canonical_key(p.a)), by_key.get(canonical_key(p.b))
        if not a or not b or a.merged_into_id or b.merged_into_id:
            continue
        if same:
            keep_name, _ = pick_canonical(a.name, b.name, evidence)
            keep, away = (a, b) if keep_name == a.name else (b, a)
            if merge(db, owner_id, keep, away, "model", "model"):
                counts["model"] += 1
        else:  # remember "different" so the same pair isn't asked about again
            db.add(KgEdge(owner_id=owner_id, src_id=a.id, dst_id=b.id, rel="not_same", source="model",
                          verified=False, provenance={}))
    db.flush()
    return counts


# ---------------------------------------------------------------- the job

def rebuild_graph(owner_id: str) -> dict[str, int]:
    """Job body: merge concepts, then derive grounded edges and competency links (steps added below)."""
    from ..db import SessionLocal
    from ..deps import user_gateway

    from . import competency, taxonomy  # noqa: F401 - register their rebuild steps

    db = SessionLocal()
    try:
        gw = user_gateway(owner_id, db)
        out = merge_concepts(db, owner_id, gw)
        for step in REBUILD_STEPS:
            out.update(step(db, owner_id, gw))
        db.commit()
        log.info("graph rebuilt: %s", out)
        return out
    finally:
        db.close()


REBUILD_STEPS: list = []  # (db, owner_id, gw) -> dict; registered by later P2 modules


# ---------------------------------------------------------------- retrieval hints

def graph_hints(db: Session, owner_id: str, document_ids: list[str]):
    """GraphHints for retrieval over these documents: every concept's names, and the passages
    (from these documents) each concept was extracted from."""
    from ..core.graph_retrieval import GraphHints
    from .concepts import COVERS

    nodes = db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == "concept")).all()
    if not nodes:
        return None
    by_id = {n.id: n for n in nodes}

    def kept_of(n: KgNode) -> KgNode:
        hops = 0
        while n.merged_into_id and n.merged_into_id in by_id and hops < 5:
            n, hops = by_id[n.merged_into_id], hops + 1
        return n

    names: dict[str, list[str]] = {}
    kept: dict[str, str] = {}
    for n in nodes:
        k = kept_of(n)
        names.setdefault(k.canonical_key, [])
        if n.name not in names[k.canonical_key]:
            names[k.canonical_key].append(n.name)
        kept[n.canonical_key] = k.canonical_key
    all_names = {key: names[kept[key]] for key in kept}
    defining: dict[str, list[str]] = {}
    for e in db.scalars(select(KgEdge).where(KgEdge.owner_id == owner_id, KgEdge.rel == COVERS)):
        prov = e.provenance or {}
        if prov.get("document_id") in document_ids and prov.get("chunk_id") and e.dst_id in by_id:
            defining.setdefault(kept_of(by_id[e.dst_id]).canonical_key, []).append(prov["chunk_id"])
    return GraphHints(names=all_names, defining_chunks=defining, kept=kept)
