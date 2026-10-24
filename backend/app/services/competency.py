"""Competency -> concept links (knowledge graph, P2): "where in my material do I learn this skill?"

Skills come from the learner's role preps (SkillMatch rows), concepts from their documents
(concepts with a `covers` edge). A `competency` node per skill links to concepts with
`maps_to` edges:
  * by rule (verified): same words, an acronym, or one name's words contained in the other's
    ("Demand forecasting" -> "Forecasting");
  * by a fast-model call for the skills no rule matched (unverified: a judgement, not a quote).
Each concept then points at the page that teaches it (the covers edge's provenance), which is
what the prep page shows as "Study in your material".

The step runs inside the rebuild_graph job and is skipped when neither the skills nor the
concepts changed since last time (a signature stored on a `meta` node), so rebuilding is cheap.
"""
from __future__ import annotations

import hashlib
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ai.gateway import BudgetExceeded, Gateway, ModelError, Request
from ..ai.prompts import COMPETENCY_SYSTEM, competency_user
from ..core.concept_merge import is_acronym_of, stem_key
from ..models import Document
from ..models_interview import SkillMatch
from ..models_kg import KgEdge, KgNode
from .concepts import COVERS
from .knowledge_graph import canonical_key

log = logging.getLogger("mindmesh.competency")

MAPS_TO = "maps_to"
MAX_SKILLS = 40
MAX_CONCEPTS = 120
MAX_LINKS_PER_SKILL = 3


def rule_match(skill: str, concept: str) -> bool:
    s, c = set(stem_key(skill).split()), set(stem_key(concept).split())
    if not s or not c:
        return False
    if s == c or is_acronym_of(skill, concept) or is_acronym_of(concept, skill):
        return True
    # One name's words inside the other's: "Demand forecasting" / "Forecasting"; "SQL" / "SQL joins".
    small, big = (s, c) if len(s) <= len(c) else (c, s)
    return small <= big and any(len(w) > 2 for w in small)


def _taught_concepts(db: Session, owner_id: str) -> list[KgNode]:
    rows = db.scalars(select(KgNode).join(KgEdge, KgEdge.dst_id == KgNode.id).where(
        KgEdge.owner_id == owner_id, KgEdge.rel == COVERS, KgNode.merged_into_id.is_(None))).all()
    return list({n.id: n for n in rows}.values())[:MAX_CONCEPTS]


def _node(db: Session, owner_id: str, kind: str, key: str, name: str) -> KgNode:
    n = db.scalar(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == kind, KgNode.canonical_key == key))
    if n is None:
        n = KgNode(owner_id=owner_id, kind=kind, canonical_key=key, name=name[:120])
        db.add(n)
        db.flush()
    return n


def map_competencies(db: Session, owner_id: str, gw: Gateway | None) -> dict[str, int]:
    skills = list(dict.fromkeys(db.scalars(select(SkillMatch.name).where(SkillMatch.owner_id == owner_id))))[:MAX_SKILLS]
    concepts = _taught_concepts(db, owner_id)
    sig = hashlib.sha1("|".join(sorted(canonical_key(s) for s in skills) + ["#"] +
                                sorted(c.canonical_key for c in concepts)).encode()).hexdigest()
    meta = _node(db, owner_id, "meta", "competency_map", "")
    if meta.name == sig:
        return {"maps_to": -1}  # unchanged
    links: dict[str, list[tuple[KgNode, bool]]] = {}
    for skill in skills:
        hits = [c for c in concepts if rule_match(skill, c.name)][:MAX_LINKS_PER_SKILL]
        links[skill] = [(c, True) for c in hits]
    unmatched = [s for s in skills if not links[s]]
    if unmatched and concepts and gw is not None:
        try:
            links.update(_model_links(gw, unmatched, concepts))
        except (BudgetExceeded, ModelError, ValueError) as exc:
            log.info("model competency mapping skipped: %s", type(exc).__name__)
            return {"maps_to": 0}  # try again next rebuild (signature not stored)
    db.execute(delete(KgEdge).where(KgEdge.owner_id == owner_id, KgEdge.rel == MAPS_TO))
    added = 0
    for skill, hits in links.items():
        if not hits:
            continue
        comp = _node(db, owner_id, "competency", canonical_key(skill), skill)
        for concept, verified in hits:
            db.add(KgEdge(owner_id=owner_id, src_id=comp.id, dst_id=concept.id, rel=MAPS_TO,
                          source="rule" if verified else "model", verified=verified, provenance={}))
            added += 1
    meta.name = sig
    db.flush()
    return {"maps_to": added}


def _model_links(gw: Gateway, skills: list[str], concepts: list[KgNode]) -> dict[str, list[tuple[KgNode, bool]]]:
    s_num = [(i + 1, s) for i, s in enumerate(skills)]
    c_num = [(i + 1, c.name) for i, c in enumerate(concepts)]

    def validate(data):
        if not isinstance(data, dict) or not isinstance(data.get("links"), list):
            raise ValueError("expected {'links': [...]}")
        out: dict[str, list[tuple[KgNode, bool]]] = {}
        for item in data["links"]:
            if not isinstance(item, dict) or not isinstance(item.get("concepts"), list):
                continue
            try:
                skill = skills[int(item["skill"]) - 1]
            except (KeyError, ValueError, TypeError, IndexError):
                continue
            picked = []
            for ci in item["concepts"][:MAX_LINKS_PER_SKILL]:
                if isinstance(ci, int) and 1 <= ci <= len(concepts):
                    picked.append((concepts[ci - 1], False))
            out[skill] = picked
        return out

    req = Request(task="competency_map", system=COMPETENCY_SYSTEM, user=competency_user(s_num, c_num), tier="fast",
                  max_tokens=2000, context={"skills": s_num, "concepts": c_num})
    return gw.complete_json(req, validate=validate)


def study_links(db: Session, owner_id: str, skill_names: list[str]) -> dict[str, list[dict]]:
    """{skill name: [{concept, document_id, document_title, page, verified}]} for skills with links."""
    keys = {canonical_key(s): s for s in skill_names}
    comps = db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == "competency",
                                            KgNode.canonical_key.in_(list(keys)))).all()
    if not comps:
        return {}
    edges = db.scalars(select(KgEdge).where(KgEdge.owner_id == owner_id, KgEdge.rel == MAPS_TO,
                                            KgEdge.src_id.in_([c.id for c in comps]))).all()
    concept_ids = {e.dst_id for e in edges}
    names = {n.id: n.name for n in db.scalars(select(KgNode).where(KgNode.id.in_(concept_ids)))}
    covers = db.scalars(select(KgEdge).where(KgEdge.owner_id == owner_id, KgEdge.rel == COVERS,
                                             KgEdge.dst_id.in_(concept_ids))).all()
    doc_ids = {(e.provenance or {}).get("document_id") for e in covers}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.owner_id == owner_id, Document.id.in_(doc_ids)))}
    where: dict[str, dict] = {}
    for e in covers:
        prov = e.provenance or {}
        d = docs.get(prov.get("document_id"))
        if d is not None and e.dst_id not in where:
            where[e.dst_id] = {"document_id": d.id, "document_title": d.title or d.filename, "page": int(prov.get("page") or 1)}
    out: dict[str, list[dict]] = {}
    by_comp = {c.id: keys[c.canonical_key] for c in comps}
    for e in edges:
        loc = where.get(e.dst_id)
        if loc:
            out.setdefault(by_comp[e.src_id], []).append({"concept": names.get(e.dst_id, ""), "verified": e.verified, **loc})
    return out


def _register() -> None:
    from .graph import REBUILD_STEPS

    if map_competencies not in REBUILD_STEPS:
        REBUILD_STEPS.append(map_competencies)


_register()
