"""Timed Today sessions: pick a few steps that fit 5, 15 or 30 minutes (CONTRACTS §7).

Pure and deterministic: no model calls, no web or database code. The service
layer gathers the inputs; this module only decides what goes into a session.

Rules (§7):

* Priority: root causes first (P2: a weak concept whose prerequisite is weak or
  untested practises the prerequisite first), then due reviews, then today's plan
  items, then the top prep gap (story or mock question), then fresh practice on
  concepts without enough answers.
  Further prep gaps and a quiz on the user's material follow as fillers.
* Time costs: review 4, quiz 5, mock_question 5, story 6, learn 8. A plan item
  uses its estimated minutes, capped at the time left.
* Greedy fill that never exceeds `minutes`. 5 minutes is exactly one step.
* Never empty when any material or prep exists: fall back to
  "Take a 5-question quiz on <doc title>" (or one interview question).
* Each step has a short plain `detail` sentence and an id that is stable for
  the same input (a hash of what the step is about).

Output steps are plain dicts shaped like the TS `SessionStep`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Sequence

MINUTES_CHOICES = (5, 15, 30)
COST = {"review": 4, "quiz": 5, "mock_question": 5, "story": 6, "learn": 8}
MIN_PLAN_ITEM_MINUTES = 3  # don't squeeze a plan item into a 1-2 minute leftover
MAX_REVIEWS = 3            # keep sessions varied: at most 3 reviews, then move on
MAX_ROOT_CAUSES = 2
MAX_FRESH = 3
MAX_PREP_STEPS = 3
MAX_DOC_FALLBACKS = 2
MIN_EVIDENCE = 3           # mirrors core.mastery.MIN_EVIDENCE (answers needed for a rating)

STORY_GAPS = ("evidence_gap", "communication_gap")
LEARN_GAPS = ("knowledge_gap", "stretch")


# ---------------- inputs ----------------

@dataclass
class DueReview:
    concept: str
    days_since: int                 # whole days since the concept was last practised
    level: str = "developing"       # mastery level: weak | developing | strong | unverified
    document_ids: list[str] = field(default_factory=list)


@dataclass
class RootCause:
    """A prerequisite to strengthen before a weak concept that builds on it (knowledge graph)."""
    concept: str                    # the prerequisite to practise
    for_concept: str                # the weak concept that builds on it
    level: str = "weak"             # prerequisite's mastery: weak | unverified
    grounded: bool = False          # the dependency is quoted from the learner's material
    document_ids: list[str] = field(default_factory=list)


@dataclass
class PlanItemIn:
    id: str
    goal_id: str
    goal_title: str
    topic: str
    estimated_minutes: int
    concept: str | None = None
    activity_type: str = "learn"


@dataclass
class PrepGap:
    prep_id: str
    skill_id: str
    name: str
    priority: str                   # effective priority: critical | high
    gap_type: str
    category: str = "technical"
    role_title: str = ""
    company: str | None = None


@dataclass
class FreshConcept:
    concept: str
    evidence_count: int = 0
    document_ids: list[str] = field(default_factory=list)


@dataclass
class DocRef:
    id: str
    title: str


@dataclass
class PrepRef:
    prep_id: str
    role_title: str = ""
    company: str | None = None


@dataclass
class BuilderInput:
    due_reviews: list[DueReview] = field(default_factory=list)
    root_causes: list[RootCause] = field(default_factory=list)
    plan_items: list[PlanItemIn] = field(default_factory=list)
    prep_gaps: list[PrepGap] = field(default_factory=list)
    fresh: list[FreshConcept] = field(default_factory=list)
    documents: list[DocRef] = field(default_factory=list)
    preps: list[PrepRef] = field(default_factory=list)

    def has_material(self) -> bool:
        return bool(self.documents or self.preps or self.prep_gaps or self.plan_items or self.due_reviews or self.fresh
                    or self.root_causes)


# ---------------- helpers ----------------

def _key(s: str | None) -> str:
    return " ".join((s or "").split()).casefold()


def step_id(prefix: str, *parts: str) -> str:
    """Stable, URL-safe id: the same subject always gets the same id."""
    digest = hashlib.sha1("\x1f".join([prefix, *parts]).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _when(days: int) -> str:
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def _role_label(role_title: str, company: str | None) -> str:
    name = (company or "").strip() or (role_title or "").strip()
    return f"your {name} role" if name else "your interview"


def _priority_word(priority: str) -> str:
    return "Critical" if priority == "critical" else "High priority"


def _quiz_target(document_ids: Sequence[str], focus: str | None) -> dict:
    return {"type": "quiz", "quiz_id": None, "document_ids": list(dict.fromkeys(document_ids)), "focus": focus}


def _step(sid: str, kind: str, title: str, detail: str, minutes: int, concept: str | None, target: dict) -> dict:
    return {"id": sid, "kind": kind, "title": title, "detail": detail, "minutes": int(minutes),
            "concept": concept, "target": target, "status": "pending"}


# ---------------- candidates ----------------

@dataclass
class _Candidate:
    """A possible step. `make(remaining)` returns the step, or None if it can't fit."""
    group: str
    make: Any  # Callable[[int], dict | None]
    doc_id: str | None = None  # set for the per-document fallback quiz


def _review(r: DueReview) -> _Candidate:
    def make(remaining: int) -> dict | None:
        if COST["review"] > remaining:
            return None
        if r.level == "weak":
            detail = f"Due for review: this was shaky when you last practised it {_when(r.days_since)}."
        else:
            detail = f"Due for review: last practised {_when(r.days_since)}."
        return _step(step_id("review", _key(r.concept)), "review", f"Review {r.concept}", detail,
                     COST["review"], r.concept, _quiz_target(r.document_ids, r.concept))
    return _Candidate("review", make)


def _root(r: RootCause) -> _Candidate:
    def make(remaining: int) -> dict | None:
        if COST["quiz"] > remaining:
            return None
        state = "is shaky" if r.level == "weak" else "hasn't been tested yet"
        source = " (your material says so)" if r.grounded else ""
        detail = f"{r.for_concept} builds on {r.concept}{source}, and {r.concept} {state}. Strengthen it first."
        return _step(step_id("root", _key(r.concept)), "quiz", f"Practise {r.concept} first", detail,
                     COST["quiz"], r.concept, _quiz_target(r.document_ids, r.concept))
    return _Candidate("root", make)


def _plan(p: PlanItemIn) -> _Candidate:
    def make(remaining: int) -> dict | None:
        if remaining < MIN_PLAN_ITEM_MINUTES:
            return None
        minutes = max(1, min(int(p.estimated_minutes or 0) or remaining, remaining))
        goal = (p.goal_title or "").strip()
        detail = f"On today's plan for your goal \"{goal}\"." if goal else "On today's plan."
        return _step(step_id("plan", p.id), "plan_item", p.topic, detail, minutes, p.concept,
                     {"type": "plan_item", "goal_id": p.goal_id, "item_id": p.id})
    return _Candidate("plan", make)


def _gap_kind(g: PrepGap) -> str:
    if g.gap_type in STORY_GAPS:
        return "story"
    if g.gap_type in LEARN_GAPS:
        return "learn"
    return "mock_question"


def _prep_gap(g: PrepGap) -> _Candidate:
    def make(remaining: int) -> dict | None:
        kind = _gap_kind(g)
        if COST[kind] > remaining:
            kind = "mock_question"  # a single question always fits a 5-minute slot
        if COST[kind] > remaining:
            return None
        detail = f"{_priority_word(g.priority)} for {_role_label(g.role_title, g.company)}."
        if kind == "story":
            title, target = f"Prepare a story that shows {g.name}", {"type": "link", "href": f"/interview/{g.prep_id}"}
        elif kind == "learn":
            title, target = f"Learn the basics of {g.name}", {"type": "link", "href": f"/interview/{g.prep_id}"}
        else:
            title, target = f"Answer one interview question on {g.name}", {"type": "interview", "prep_id": g.prep_id, "session_id": None}
        return _step(step_id("prep", g.prep_id, g.skill_id), kind, title, detail, COST[kind], g.name, target)
    return _Candidate("prep", make)


def _fresh(f: FreshConcept) -> _Candidate:
    def make(remaining: int) -> dict | None:
        if COST["quiz"] > remaining:
            return None
        n = max(0, int(f.evidence_count))
        if n == 0:
            detail = "Not enough answers yet: a few questions will show where you stand."
        else:
            more = max(1, MIN_EVIDENCE - n)
            detail = f"Not enough answers yet: {more} more and we can tell how well you know it."
        return _step(step_id("quiz", _key(f.concept)), "quiz", f"Practise {f.concept}", detail,
                     COST["quiz"], f.concept, _quiz_target(f.document_ids, f.concept))
    return _Candidate("fresh", make)


def _doc_quiz(d: DocRef) -> _Candidate:
    def make(remaining: int) -> dict | None:
        if COST["quiz"] > remaining:
            return None
        title = (d.title or "").strip() or "your material"
        return _step(step_id("doc", d.id), "quiz", f"Take a 5-question quiz on {title}",
                     "A quick quiz shows what you already know from this material.",
                     COST["quiz"], None, _quiz_target([d.id], None))
    return _Candidate("doc", make, d.id)


def _prep_question(p: PrepRef) -> _Candidate:
    def make(remaining: int) -> dict | None:
        if COST["mock_question"] > remaining:
            return None
        label = _role_label(p.role_title, p.company)
        return _step(step_id("prepq", p.prep_id), "mock_question", "Answer one interview question",
                     f"Keeps your practice for {label} going.", COST["mock_question"], None,
                     {"type": "interview", "prep_id": p.prep_id, "session_id": None})
    return _Candidate("prep_fallback", make)


def _candidates(inp: BuilderInput) -> list[_Candidate]:
    out: list[_Candidate] = []
    seen_concepts: set[str] = set()

    roots = 0
    for rc in inp.root_causes:
        k = _key(rc.concept)
        if not k or k in seen_concepts or roots >= MAX_ROOT_CAUSES:
            continue
        seen_concepts.add(k)
        roots += 1
        out.append(_root(rc))

    reviews = 0
    for r in inp.due_reviews:
        k = _key(r.concept)
        if not k or k in seen_concepts or reviews >= MAX_REVIEWS:
            continue
        seen_concepts.add(k)
        reviews += 1
        out.append(_review(r))

    seen_items: set[str] = set()
    for p in inp.plan_items:
        if p.id in seen_items:
            continue
        seen_items.add(p.id)
        out.append(_plan(p))

    gaps: list[PrepGap] = []
    seen_gaps: set[tuple[str, str]] = set()
    for g in inp.prep_gaps:
        k = (g.prep_id, g.skill_id)
        if k not in seen_gaps and _key(g.name):
            seen_gaps.add(k)
            gaps.append(g)
    gaps = gaps[:MAX_PREP_STEPS]
    if gaps:
        out.append(_prep_gap(gaps[0]))

    fresh = 0
    for f in inp.fresh:
        k = _key(f.concept)
        if not k or k in seen_concepts or fresh >= MAX_FRESH:
            continue
        seen_concepts.add(k)
        fresh += 1
        out.append(_fresh(f))

    out.extend(_prep_gap(g) for g in gaps[1:])

    if inp.preps and not gaps:
        out.append(_prep_question(inp.preps[0]))

    seen_docs: set[str] = set()
    for d in inp.documents:
        if d.id in seen_docs:
            continue
        seen_docs.add(d.id)
        if len(seen_docs) > MAX_DOC_FALLBACKS:
            break
        out.append(_doc_quiz(d))
    return out


# ---------------- builder ----------------

def build_session(minutes: int, inp: BuilderInput) -> list[dict]:
    """Greedy fill in priority order; never exceeds `minutes`; 5 minutes is exactly one step."""
    if minutes not in MINUTES_CHOICES:
        raise ValueError("minutes must be 5, 15 or 30")
    remaining = minutes
    steps: list[dict] = []
    ids: set[str] = set()
    covered_docs: set[str] = set()
    for cand in _candidates(inp):
        if cand.doc_id is not None and cand.doc_id in covered_docs:
            continue  # filler only for material no earlier quiz or review step covers
        step = cand.make(remaining)
        if step is None or step["id"] in ids or step["minutes"] > remaining:
            continue
        steps.append(step)
        ids.add(step["id"])
        remaining -= step["minutes"]
        if step["target"]["type"] == "quiz":
            covered_docs.update(step["target"]["document_ids"])
        if minutes == 5 or remaining <= 0:
            break
    return steps


def build_suggestions(inp: BuilderInput) -> dict[str, list[dict]]:
    """A ready-made plan for each time choice (TodayPreview.suggestions)."""
    return {str(m): build_session(m, inp) for m in MINUTES_CHOICES}


__all__ = [
    "COST", "MINUTES_CHOICES", "BuilderInput", "DocRef", "DueReview", "FreshConcept", "PlanItemIn", "PrepGap",
    "PrepRef", "RootCause", "build_session", "build_suggestions", "step_id",
]
