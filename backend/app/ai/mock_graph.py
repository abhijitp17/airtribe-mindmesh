"""Offline graph tasks: concept merge decisions (same stemmed words, in any order)."""
from __future__ import annotations

from .mock import register_mock


@register_mock("concept_merge")
def _concept_merge(ctx: dict) -> dict:
    from ..core.concept_merge import stem_key

    out = []
    for i, a, b in ctx.get("pairs", []):
        out.append({"id": i, "same": sorted(stem_key(a).split()) == sorted(stem_key(b).split())})
    return {"decisions": out}


@register_mock("competency_map")
def _competency_map(ctx: dict) -> dict:
    from ..core.concept_merge import jaccard

    links = []
    for si, skill in ctx.get("skills", []):
        hits = sorted(((jaccard(skill, c), ci) for ci, c in ctx.get("concepts", [])), reverse=True)
        links.append({"skill": si, "concepts": [ci for score, ci in hits[:3] if score >= 0.34]})
    return {"links": links}
