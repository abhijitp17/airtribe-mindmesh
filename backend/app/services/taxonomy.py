"""Shared skill taxonomy (P3, policy: DECISIONS #54).

The taxonomy is curated reference data versioned with the code (`app/data/taxonomy.json`), read-only
at runtime and never built from user content. Each user's own graph links to it: a private
`taxonomy` node per skill they touch, with `in_taxonomy` edges from their concepts and interview
skills (competencies). No user's names, material or mastery are visible to anyone else.

The skill profile combines, per taxonomy skill: which of the learner's concepts and job skills
map to it, their mastery (knowledge tracing on those concepts' answers), and the roles asking for it.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.concept_merge import stem_key
from ..models_kg import KgEdge, KgNode
from .competency import rule_match
from .knowledge_graph import canonical_key

IN_TAXONOMY = "in_taxonomy"
DATA = Path(__file__).resolve().parents[1] / "data" / "taxonomy.json"
LEVEL_ORDER = {"strong": 3, "developing": 2, "weak": 1, "unverified": 0}


@lru_cache(maxsize=1)
def load() -> dict:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    for s in data["skills"]:
        s["_keys"] = {stem_key(n) for n in [s["name"], *s["aliases"]]}
    return data


def match(name: str) -> str | None:
    """The taxonomy skill a name belongs to: an exact (stemmed) name or alias first, then a word-level rule."""
    key = stem_key(name)
    if not key:
        return None
    skills = load()["skills"]
    for s in skills:
        if key in s["_keys"]:
            return s["slug"]
    for s in skills:
        if any(rule_match(name, a) for a in [s["name"], *s["aliases"]] if len(a.split()) > 1 or len(name.split()) > 1):
            return s["slug"]
    return None


def map_taxonomy(db: Session, owner_id: str, gw=None) -> dict[str, int]:
    """Rebuild step (services/graph.REBUILD_STEPS): link the user's concepts and skills to the taxonomy."""
    nodes = db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind.in_(("concept", "competency")),
                                            KgNode.merged_into_id.is_(None))).all()
    sig = hashlib.sha1(("|".join(sorted(f"{n.kind}:{n.canonical_key}" for n in nodes)) + load()["version"]).encode()).hexdigest()
    meta = db.scalar(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == "meta", KgNode.canonical_key == "taxonomy_map"))
    if meta is None:
        meta = KgNode(owner_id=owner_id, kind="meta", canonical_key="taxonomy_map", name="")
        db.add(meta)
        db.flush()
    if meta.name == sig:
        return {"in_taxonomy": -1}
    db.execute(delete(KgEdge).where(KgEdge.owner_id == owner_id, KgEdge.rel == IN_TAXONOMY))
    by_slug = {s["slug"]: s for s in load()["skills"]}
    tax_nodes = {n.canonical_key: n for n in db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == "taxonomy"))}
    added = 0
    for n in nodes:
        slug = match(n.name)
        if slug is None:
            continue
        t = tax_nodes.get(slug)
        if t is None:
            t = KgNode(owner_id=owner_id, kind="taxonomy", canonical_key=slug, name=by_slug[slug]["name"][:120])
            db.add(t)
            db.flush()
            tax_nodes[slug] = t
        db.add(KgEdge(owner_id=owner_id, src_id=n.id, dst_id=t.id, rel=IN_TAXONOMY, source="taxonomy", verified=True,
                      provenance={"taxonomy_version": load()["version"]}))
        added += 1
    meta.name = sig
    db.flush()
    return {"in_taxonomy": added}


def skill_profile(db: Session, owner_id: str) -> list[dict]:
    """Per taxonomy skill the learner touches: concepts, job skills, best mastery level, roles asking for it."""
    from ..core.mastery import estimate
    from ..models_interview import JobProfile, RolePrep, SkillMatch
    from .engagement import _evidence

    tax = {n.id: n for n in db.scalars(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == "taxonomy"))}
    if not tax:
        return []
    edges = db.scalars(select(KgEdge).where(KgEdge.owner_id == owner_id, KgEdge.rel == IN_TAXONOMY,
                                            KgEdge.dst_id.in_(list(tax)))).all()
    src = {n.id: n for n in db.scalars(select(KgNode).where(KgNode.id.in_([e.src_id for e in edges])))}
    evidence = {canonical_key(c): a for c, a in _evidence(owner_id, db).by_concept.items()}
    roles_by_skill: dict[str, set[str]] = {}
    for name, role in db.execute(select(SkillMatch.name, JobProfile.role_title)
                                 .join(RolePrep, RolePrep.id == SkillMatch.prep_id)
                                 .join(JobProfile, JobProfile.id == RolePrep.job_id)
                                 .where(SkillMatch.owner_id == owner_id)):
        roles_by_skill.setdefault(canonical_key(name), set()).add(role or "")
    category = {s["slug"]: s["category"] for s in load()["skills"]}
    out = []
    for tid, t in tax.items():
        mine = [src[e.src_id] for e in edges if e.dst_id == tid and e.src_id in src]
        concepts = sorted({n.name for n in mine if n.kind == "concept"})
        skills = sorted({n.name for n in mine if n.kind == "competency"})
        levels = [estimate(c, evidence[canonical_key(c)]).level for c in concepts if canonical_key(c) in evidence]
        level = max(levels, key=lambda lv: LEVEL_ORDER[lv]) if levels else "unverified"
        roles = sorted({r for s in skills for r in roles_by_skill.get(canonical_key(s), set()) if r})
        out.append({"slug": t.canonical_key, "name": t.name, "category": category.get(t.canonical_key, "domain"),
                    "level": level, "concepts": concepts, "job_skills": skills, "roles": roles})
    out.sort(key=lambda s: (-len(s["roles"]), -LEVEL_ORDER[s["level"]], s["name"]))
    return out


def _register() -> None:
    from .graph import REBUILD_STEPS

    if map_taxonomy not in REBUILD_STEPS:
        REBUILD_STEPS.append(map_taxonomy)


_register()
