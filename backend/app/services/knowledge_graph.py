"""Knowledge graph, P1 foundation: concept nodes and prerequisite edges (models_kg.py).

Concepts come from what the product already produces: quiz question concepts and
planner topics. Prerequisite edges come from the planner, which used to throw them
away after scheduling. Every query filters by owner_id (RLS is the second layer).

Edges here are `verified=False`: the planner's ordering, not yet grounded in a page
quote. P2 adds grounding, concept merging (same_as) and maps_to links.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence

from sqlalchemy import func, literal, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.planner import TopicSpec
from ..models_kg import KgEdge, KgNode

PREREQUISITE_OF = "prerequisite_of"
MAX_CHAIN_DEPTH = 5
_DROP = {"'", "’", "‘", "`", "´"}  # "Little's Law" and "Littles Law" are one concept


def canonical_key(name: str) -> str:
    """Case-, punctuation- and spacing-insensitive identity for a concept name. Unicode-safe."""
    s = unicodedata.normalize("NFKC", name or "").casefold()
    out = []
    for c in s:
        if c in _DROP:
            continue
        cat = unicodedata.category(c)
        # Keep letters, numbers and combining marks (Devanagari vowel signs are Mc/Mn); '+' and '#' for C++ / C#.
        out.append(c if cat[0] in "LNM" or c in "+#" else " ")
    return " ".join("".join(out).split())[:120]


def upsert_concepts(db: Session, owner_id: str, names: Iterable[str]) -> dict[str, KgNode]:
    """Return {canonical_key: node} for every non-empty name, creating missing nodes."""
    wanted: dict[str, str] = {}
    for n in names:
        display = " ".join((n or "").split())[:120]
        key = canonical_key(display)
        if key and key not in wanted:
            wanted[key] = display
    if not wanted:
        return {}
    found = _nodes_by_key(db, owner_id, wanted)
    for key, display in wanted.items():
        if key in found:
            continue
        node = KgNode(owner_id=owner_id, kind="concept", name=display, canonical_key=key)
        try:
            with db.begin_nested():  # a concurrent request may have created it
                db.add(node)
            found[key] = node
        except IntegrityError:
            found.update(_nodes_by_key(db, owner_id, {key: display}))
    return {k: resolve(db, n) for k, n in found.items()}


def resolve(db: Session, node: KgNode, max_hops: int = 5) -> KgNode:
    """The node a merged concept now lives in (itself if it wasn't merged)."""
    for _ in range(max_hops):
        if not node.merged_into_id:
            break
        nxt = db.get(KgNode, node.merged_into_id)
        if nxt is None or nxt.owner_id != node.owner_id:
            break
        node = nxt
    return node


def _nodes_by_key(db: Session, owner_id: str, keys: Iterable[str]) -> dict[str, KgNode]:
    rows = db.scalars(select(KgNode).where(
        KgNode.owner_id == owner_id, KgNode.kind == "concept", KgNode.canonical_key.in_(list(keys)))).all()
    return {n.canonical_key: n for n in rows}


def record_prerequisites(db: Session, owner_id: str, topics: Sequence[TopicSpec], provenance: dict) -> int:
    """Save the planner's "topic B builds on topic A" as A -prerequisite_of-> B between concepts.

    Returns how many new edges were added. Idempotent: existing edges are left alone.
    """
    concept_of = {t.topic.casefold(): (t.concept or t.topic) for t in topics}
    pairs: list[tuple[str, str]] = []
    for t in topics:
        for p in t.prerequisites:
            src = concept_of.get(p.casefold())
            dst = t.concept or t.topic
            if src and canonical_key(src) != canonical_key(dst):
                pairs.append((src, dst))
    nodes = upsert_concepts(db, owner_id, [t.concept or t.topic for t in topics])
    if not pairs:
        return 0
    ids = {(nodes[canonical_key(s)].id, nodes[canonical_key(d)].id) for s, d in pairs}
    existing = set(db.execute(select(KgEdge.src_id, KgEdge.dst_id).where(
        KgEdge.owner_id == owner_id, KgEdge.rel == PREREQUISITE_OF,
        tuple_(KgEdge.src_id, KgEdge.dst_id).in_(list(ids)))).all())
    new = ids - {tuple(e) for e in existing}
    for src_id, dst_id in new:
        db.add(KgEdge(owner_id=owner_id, src_id=src_id, dst_id=dst_id, rel=PREREQUISITE_OF,
                      source="planner", verified=False, provenance=dict(provenance)))
    db.flush()
    return len(new)


def prerequisite_chain(db: Session, owner_id: str, concept: str, max_depth: int = MAX_CHAIN_DEPTH) -> list[tuple[str, int]]:
    """Everything `concept` builds on, nearest first: [(name, depth)]. Depth-bounded, so cycles terminate."""
    target = db.scalar(select(KgNode.id).where(
        KgNode.owner_id == owner_id, KgNode.kind == "concept", KgNode.canonical_key == canonical_key(concept)))
    if target is None:
        return []
    base = (select(KgEdge.src_id.label("node_id"), literal(1).label("depth"))
            .where(KgEdge.owner_id == owner_id, KgEdge.rel == PREREQUISITE_OF, KgEdge.dst_id == target)
            .cte("chain", recursive=True))
    step = (select(KgEdge.src_id, base.c.depth + 1)
            .join(base, KgEdge.dst_id == base.c.node_id)
            .where(KgEdge.owner_id == owner_id, KgEdge.rel == PREREQUISITE_OF, base.c.depth < max_depth))
    chain = base.union(step)
    rows = db.execute(
        select(KgNode.name, func.min(chain.c.depth).label("depth"))
        .join(chain, KgNode.id == chain.c.node_id)
        .where(KgNode.owner_id == owner_id, KgNode.id != target)
        .group_by(KgNode.id, KgNode.name)
        .order_by("depth", KgNode.name)
    ).all()
    return [(r.name, r.depth) for r in rows]


def direct_prerequisite_verified(db: Session, owner_id: str, before: str, after: str) -> bool:
    """True when `before -> after` is a prerequisite edge grounded in the learner's material."""
    keys = {canonical_key(before), canonical_key(after)}
    nodes = {n.canonical_key: n for n in db.scalars(select(KgNode).where(
        KgNode.owner_id == owner_id, KgNode.kind == "concept", KgNode.canonical_key.in_(list(keys))))}
    a, b = nodes.get(canonical_key(before)), nodes.get(canonical_key(after))
    if a is None or b is None:
        return False
    return bool(db.scalar(select(KgEdge.verified).where(
        KgEdge.owner_id == owner_id, KgEdge.rel == PREREQUISITE_OF, KgEdge.src_id == resolve(db, a).id,
        KgEdge.dst_id == resolve(db, b).id)))


def with_graph_prerequisites(db: Session, owner_id: str, topics: Sequence[TopicSpec]) -> list[TopicSpec]:
    """Add prerequisites the learner's material states (verified edges) between topics in this plan.

    The planner's own guesses are already in `topics`; this only adds grounded "builds on" links,
    so the schedule puts foundations first even when the model's proposal missed them.
    """
    import dataclasses

    out = [dataclasses.replace(t, prerequisites=list(t.prerequisites)) for t in topics]
    concept_of = {t.topic: canonical_key(t.concept or t.topic) for t in out}
    nodes = {n.canonical_key: resolve(db, n) for n in db.scalars(select(KgNode).where(
        KgNode.owner_id == owner_id, KgNode.kind == "concept", KgNode.canonical_key.in_(list(set(concept_of.values())))))}
    ids = {t.topic: nodes[k].id for t, k in ((t, concept_of[t.topic]) for t in out) if k in nodes}
    if len(ids) < 2:
        return out
    edges = set(db.execute(select(KgEdge.src_id, KgEdge.dst_id).where(
        KgEdge.owner_id == owner_id, KgEdge.rel == PREREQUISITE_OF, KgEdge.verified.is_(True),
        KgEdge.src_id.in_(list(ids.values())), KgEdge.dst_id.in_(list(ids.values())))).all())
    for t in out:
        for other in out:
            if other is not t and (ids.get(other.topic), ids.get(t.topic)) in edges and other.topic not in t.prerequisites:
                t.prerequisites.append(other.topic)
    return out
