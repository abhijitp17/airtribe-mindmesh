"""Graph-aware retrieval (P2). Pure: the service layer builds `GraphHints` from the user's graph.

Two small, measurable nudges on top of hybrid retrieval, never replacing it:

* Alias expansion: a question that names a concept by one of its names ("WIP") also searches
  for the others ("work in process"), from concept merges. Only the search query changes; the
  tutor still sees the learner's exact question.
* Defining passage: when the question names a concept, the passage the concept was extracted
  from (its `covers` provenance) is brought into the top results, but only if retrieval already
  found it relevant among its candidates, so the coverage gate still decides "not found".
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..services.knowledge_graph import canonical_key


@dataclass
class GraphHints:
    names: dict[str, list[str]] = field(default_factory=dict)  # canonical key of any name -> all names of that concept
    defining_chunks: dict[str, list[str]] = field(default_factory=dict)  # canonical key of the kept name -> chunk ids
    kept: dict[str, str] = field(default_factory=dict)  # canonical key of any name -> kept name's canonical key


def mentioned(question: str, hints: GraphHints) -> list[str]:
    """Canonical keys of concepts named in the question (whole words; longest names first)."""
    q = canonical_key(question)
    padded = f" {q} "
    found: list[str] = []
    for key in sorted(hints.names, key=len, reverse=True):
        if len(key) >= 2 and f" {key} " in padded:
            kept = hints.kept.get(key, key)
            if kept not in found:
                found.append(kept)
            padded = padded.replace(f" {key} ", " ")  # "work in process" shouldn't also match "process"
    return found


def expand_query(question: str, hints: GraphHints | None) -> str:
    if not hints:
        return question
    extra: list[str] = []
    for kept in mentioned(question, hints):
        for name in hints.names.get(kept, []):
            if canonical_key(name) not in canonical_key(question) and name not in extra:
                extra.append(name)
    return f"{question} ({'; '.join(extra)})" if extra else question


def defining_chunks(question: str, hints: GraphHints | None) -> list[str]:
    if not hints:
        return []
    out: list[str] = []
    for kept in mentioned(question, hints):
        for cid in hints.defining_chunks.get(kept, []):
            if cid not in out:
                out.append(cid)
    return out


def promote(hit_ids: list[str], candidate_ids: list[str], wanted: list[str], k: int) -> list[str]:
    """Top-k ids with any `wanted` chunk that retrieval ranked as a candidate moved into the top k
    (replacing the lowest-ranked hits). Order otherwise unchanged."""
    top = list(hit_ids[:k])
    for cid in wanted:
        if cid in top or cid not in candidate_ids:
            continue
        if len(top) >= k:
            top.pop()
        top.append(cid)
    return top

