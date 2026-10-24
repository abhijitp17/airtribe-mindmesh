"""Concept merging rules (knowledge graph, P2). Pure: no database, no model.

The same idea often arrives under different names: from quiz questions ("WIP"), planner
topics ("Work in process") and documents ("work-in-process inventory"). `canonical_key`
already folds case, punctuation and spacing. These rules find the remaining *certain*
duplicates; a merge that is wrong makes mastery and prerequisites wrong, so they favour
precision (evals/gold/concept_merges.jsonl gates it in CI):

  plural        "Queue" / "Queues", "Bottleneck analysis" / "Bottlenecks analysis"
  acronym       "WIP" / "Work in process" (initials, with or without short function words)
  parenthetical "Work in process (WIP)" is the same as both "Work in process" and "WIP"

Pairs that are merely similar (most words shared) are returned separately as candidates for
a model to confirm, never merged by rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

from ..services.knowledge_graph import canonical_key

_FUNCTION = {"of", "the", "a", "an", "and", "in", "on", "for", "to", "with", "by", "at", "or", "vs"}
_PAREN = re.compile(r"^(?P<main>.+?)\s*\((?P<inner>[^()]{1,40})\)\s*$")
_INVARIANT = {"analysis", "basis", "thesis", "series", "species", "status", "process", "business", "class", "gas", "bus",
              "physics", "economics", "mathematics", "statistics", "logistics", "news", "lens", "bias", "chaos"}


@dataclass(frozen=True)
class MergePair:
    a: str  # display names as given
    b: str
    reason: str  # plural | acronym | parenthetical | similar


def singular(word: str) -> str:
    w = word
    if len(w) <= 3 or w in _INVARIANT or not w.isalpha():
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("sses", "shes", "ches", "xes")):
        return w[:-2]
    if w.endswith("ss") or w.endswith("us") or w.endswith("is"):
        return w
    if w.endswith("s"):
        return w[:-1]
    return w


def tokens(name: str) -> list[str]:
    return canonical_key(name).split()


def stem_key(name: str) -> str:
    return " ".join(singular(t) for t in tokens(name))


def _initials(words: list[str]) -> str:
    return "".join(w[0] for w in words if w)


def is_acronym_of(short: str, long: str) -> bool:
    """'WIP' / 'Work in process'. The short form must look like an acronym (one word, 2-6 letters,
    written in capitals), and the long form must have at least as many words as it has letters."""
    s = short.strip()
    if not re.fullmatch(r"[A-Z][A-Za-z]{1,5}s?", s) or sum(c.isupper() for c in s) < 2:
        return False
    letters = s.rstrip("s").lower() if s.endswith("s") and s[:-1].isupper() else s.lower()
    words = tokens(long)
    if len(words) < 2 or len(words) < len(letters):
        return False
    content = [w for w in words if w not in _FUNCTION]
    return letters in (_initials(words), _initials(content))


def split_parenthetical(name: str) -> tuple[str, str] | None:
    m = _PAREN.match(name.strip())
    if not m:
        return None
    return m.group("main").strip(), m.group("inner").strip()


def jaccard(a: str, b: str) -> float:
    x, y = set(stem_key(a).split()), set(stem_key(b).split())
    return len(x & y) / len(x | y) if x and y else 0.0


def rule_pairs(names: list[str]) -> list[MergePair]:
    """Certain duplicates among `names` (display names). Each unordered pair at most once."""
    out: list[MergePair] = []
    seen: set[frozenset[str]] = set()

    def add(a: str, b: str, reason: str) -> None:
        if canonical_key(a) == canonical_key(b):
            return
        key = frozenset((canonical_key(a), canonical_key(b)))
        if key not in seen:
            seen.add(key)
            out.append(MergePair(a, b, reason))

    stems: dict[str, str] = {}
    for n in names:
        st = stem_key(n)
        if st and st in stems:
            add(stems[st], n, "plural")
        elif st:
            stems[st] = n
    by_key = {canonical_key(n): n for n in names}
    for n in names:
        parts = split_parenthetical(n)
        if parts:
            main, inner = parts
            for other in (main, inner):
                hit = by_key.get(canonical_key(other)) or next((m for m in names if stem_key(m) == stem_key(other)), None)
                if hit:
                    add(hit, n, "parenthetical")
            if is_acronym_of(inner, main):
                for a in names:
                    for b in names:
                        if canonical_key(a) == canonical_key(inner) and stem_key(b) == stem_key(main):
                            add(a, b, "acronym")
    expansions: dict[str, set[str]] = {}
    for a, b in combinations(names, 2):
        for short, long in ((a, b), (b, a)):
            if is_acronym_of(short, long):
                expansions.setdefault(short, set()).add(stem_key(long))
    for a, b in combinations(names, 2):
        for short, long in ((a, b), (b, a)):
            # An acronym with two different expansions here ("CV": coefficient of variation, curriculum vitae)
            # is ambiguous: leave it to the model.
            if is_acronym_of(short, long) and len(expansions.get(short, ())) == 1:
                add(short, long, "acronym")
    return out


def ambiguous_acronyms(names: list[str]) -> list[MergePair]:
    """Acronym pairs not merged by rule because the acronym has several expansions in this graph."""
    certain = {frozenset((canonical_key(p.a), canonical_key(p.b))) for p in rule_pairs(names)}
    return [MergePair(short, long, "similar") for a, b in combinations(names, 2) for short, long in ((a, b), (b, a))
            if is_acronym_of(short, long) and frozenset((canonical_key(short), canonical_key(long))) not in certain]


def similar_pairs(names: list[str], threshold: float = 0.5, limit: int = 40) -> list[MergePair]:
    """Pairs sharing most of their words but not certain duplicates: for a model to confirm."""
    certain = {frozenset((canonical_key(p.a), canonical_key(p.b))) for p in rule_pairs(names)}
    scored = []
    for a, b in combinations(names, 2):
        if frozenset((canonical_key(a), canonical_key(b))) in certain or canonical_key(a) == canonical_key(b):
            continue
        if min(len(tokens(a)), len(tokens(b))) < 2:
            continue
        j = jaccard(a, b)
        if j >= threshold:
            scored.append((j, MergePair(a, b, "similar")))
    scored.sort(key=lambda t: -t[0])
    return (ambiguous_acronyms(names) + [p for _, p in scored])[:limit]


def pick_canonical(a: str, b: str, evidence: dict[str, int] | None = None) -> tuple[str, str]:
    """(keep, merge_away). More evidence wins; then the spelled-out form over an acronym or parenthetical;
    then the shorter plain name (singular)."""
    ev = evidence or {}
    ea, eb = ev.get(canonical_key(a), 0), ev.get(canonical_key(b), 0)
    if ea != eb:
        return (a, b) if ea > eb else (b, a)
    def rank(n: str) -> tuple:
        acronym = 1 if re.fullmatch(r"[A-Z]{2,6}s?", n.strip()) else 0
        paren = 1 if split_parenthetical(n) else 0
        plural = 1 if stem_key(n) != " ".join(tokens(n)) else 0
        return (acronym, paren, plural, len(n), n)
    return (a, b) if rank(a) <= rank(b) else (b, a)
