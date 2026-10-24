"""Mock-interview engine: question selection, rubrics, grading rules, summary (PRD §7.5).

This is a pure state machine. Given the turns so far it decides the next step
(ask a follow-up, ask the next question, or finish), which competency and
category to ask about, and how a model's rubric judgement becomes a score.
The service layer does the model calls; every rule a user could dispute
lives here:

* Scores are recomputed from per-criterion judgements (the model's own
  number is ignored) and the verdict is banded in code.
* At most one follow-up per main question, and only when the evaluation lists
  missing details or scores below 0.6.
* Feedback must not invent candidate facts: list items that cite numbers the
  candidate never said are dropped (`_drop_invented_numbers`).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .assessment import normalize_rubric_grade
from .interview_deepdive import analyse_claim, template_questions
from .interview_matrix import GAP_SEVERITY, PRIORITY_ORDER

RUBRIC_VERSION = "interview-rubric@1"
FOCI = ("mixed", "technical", "behavioral", "resume", "case")
QUESTION_CATEGORIES = ("technical", "behavioral", "case", "resume_deep_dive", "role_specific")
FOLLOW_UP_THRESHOLD = 0.6
VERDICT_BANDS = ((0.8, "strong"), (0.6, "adequate"))
MAX_LIST_ITEMS = 5

# Category order per focus; the n-th main question uses ROTATION[n % len].
ROTATION: dict[str, tuple[str, ...]] = {
    "mixed": ("technical", "behavioral", "resume_deep_dive", "role_specific", "case"),
    "technical": ("technical", "case", "technical", "role_specific"),
    "behavioral": ("behavioral", "behavioral", "resume_deep_dive"),
    "resume": ("resume_deep_dive", "resume_deep_dive", "behavioral"),
    "case": ("case", "case", "technical"),
}
# Which competency categories each question category draws on, in preference order.
ELIGIBLE: dict[str, tuple[str, ...]] = {
    "technical": ("technical", "tool", "domain"),
    "case": ("domain", "technical", "tool"),
    "role_specific": ("domain", "leadership", "technical", "tool", "communication", "behavioral"),
    "behavioral": ("behavioral", "leadership", "communication"),
    "resume_deep_dive": (),
}

RUBRICS: dict[str, list[dict]] = {
    "technical": [
        {"criterion": "Explains the core concept correctly", "points": 3},
        {"criterion": "Applies it to a concrete situation or example", "points": 2},
        {"criterion": "Discusses trade-offs, limits or alternatives", "points": 2},
        {"criterion": "Answer is clearly structured", "points": 1},
    ],
    "behavioral": [
        {"criterion": "Situation: sets the context", "points": 1},
        {"criterion": "Task: states their own goal or responsibility", "points": 1},
        {"criterion": "Action: describes what they personally did", "points": 2},
        {"criterion": "Result: gives a concrete, ideally measurable outcome", "points": 2},
        {"criterion": "Reflection: says what they learned or would change", "points": 1},
        {"criterion": "Specificity: real names, numbers and details rather than generalities", "points": 1},
    ],
    "case": [
        {"criterion": "Clarifies the goal and states assumptions", "points": 2},
        {"criterion": "Uses a structured approach", "points": 2},
        {"criterion": "Reasons quantitatively where possible", "points": 2},
        {"criterion": "Makes a recommendation and names risks", "points": 2},
    ],
    "resume_deep_dive": [
        {"criterion": "Defines the claim or metric precisely", "points": 2},
        {"criterion": "States the baseline and how it was measured", "points": 2},
        {"criterion": "Explains their personal contribution", "points": 2},
        {"criterion": "Explains the method and trade-offs", "points": 1},
        {"criterion": "Addresses attribution and limitations", "points": 1},
    ],
    "role_specific": [
        {"criterion": "Shows relevant knowledge of the role and domain", "points": 2},
        {"criterion": "Connects to their own experience", "points": 2},
        {"criterion": "Gives a concrete example", "points": 2},
        {"criterion": "Answer is clearly structured", "points": 1},
    ],
}
STAR_KEYS = ("situation", "task", "action", "result", "reflection")


# ---------------- state ----------------

@dataclass(frozen=True)
class Candidate:
    """A competency the interview can target, taken from the prep's matrix."""
    competency_id: str
    name: str
    category: str
    priority: str
    gap_type: str
    evidence: tuple[str, ...] = ()
    jd_quote: str = ""


@dataclass(frozen=True)
class ResumeBulletRef:
    bullet_id: str
    text: str
    role_title: str
    competency_id: str | None = None
    competency_name: str | None = None


@dataclass
class TurnState:
    kind: str  # question | follow_up
    category: str
    question: str
    competency_id: str | None = None
    competency_name: str | None = None
    answer: str | None = None
    evaluation: dict | None = None


@dataclass
class SessionState:
    focus: str
    target_questions: int
    turns: list[TurnState] = field(default_factory=list)

    @property
    def main_questions(self) -> int:
        return sum(1 for t in self.turns if t.kind == "question")


@dataclass(frozen=True)
class QuestionPlan:
    """What to ask next; the model (or the template) turns it into words."""
    category: str
    competency_id: str | None
    competency_name: str | None
    competency_category: str | None = None
    gap_type: str | None = None
    evidence: tuple[str, ...] = ()
    jd_quote: str = ""
    bullet: str | None = None
    variant: int = 0


@dataclass(frozen=True)
class NextStep:
    action: str  # follow_up | question | complete
    plan: QuestionPlan | None = None


# ---------------- selection ----------------

def _category_for(state: SessionState, bullets: list[ResumeBulletRef]) -> str:
    rotation = ROTATION.get(state.focus, ROTATION["mixed"])
    category = rotation[state.main_questions % len(rotation)]
    if category == "resume_deep_dive" and not _probeable(bullets):
        return "behavioral"
    return category


def _probeable(bullets: list[ResumeBulletRef]) -> list[ResumeBulletRef]:
    return [b for b in bullets if analyse_claim(b.text).probeable]


def _asked_counts(state: SessionState) -> Counter:
    return Counter(t.competency_id for t in state.turns if t.kind == "question" and t.competency_id)


def _pick_candidate(category: str, candidates: list[Candidate], asked: Counter) -> Candidate | None:
    """Least-asked first, then highest priority, then most severe gap; deterministic tie-break by name."""
    if not candidates:
        return None
    wanted = ELIGIBLE.get(category, ())
    pool = [c for c in candidates if c.category in wanted] or list(candidates)
    return min(pool, key=lambda c: (
        asked[c.competency_id], PRIORITY_ORDER.get(c.priority, 3), -GAP_SEVERITY.get(c.gap_type, 0.0), c.name.lower(),
    ))


def _pick_bullet(state: SessionState, bullets: list[ResumeBulletRef], priority_of: dict[str, str]) -> ResumeBulletRef:
    """Prefer unasked bullets with a metric (the claims interviewers probe hardest), then priority."""
    asked_text = " ".join(t.question.lower() for t in state.turns)
    probeable = _probeable(bullets)
    fresh = [b for b in probeable if b.text.lower()[:60] not in asked_text] or probeable
    return min(fresh, key=lambda b: (
        analyse_claim(b.text).metric is None,
        PRIORITY_ORDER.get(priority_of.get(b.competency_id or "", "low"), 3),
        probeable.index(b),
    ))


def select_question(state: SessionState, candidates: list[Candidate], bullets: list[ResumeBulletRef]) -> QuestionPlan:
    """Choose category (from focus rotation) and target (competency or resume bullet)."""
    category = _category_for(state, bullets)
    variant = sum(1 for t in state.turns if t.kind == "question" and t.category == category)
    if category == "resume_deep_dive":
        b = _pick_bullet(state, bullets, {c.competency_id: c.priority for c in candidates})
        return QuestionPlan(category, b.competency_id, b.competency_name, bullet=b.text, evidence=(b.text,), variant=variant)
    c = _pick_candidate(category, candidates, _asked_counts(state))
    if c is None:
        return QuestionPlan(category, None, None, variant=variant)
    return QuestionPlan(category, c.competency_id, c.name, c.category, c.gap_type, c.evidence[:3], c.jd_quote, variant=variant)


def needs_follow_up(state: SessionState) -> bool:
    """Max one follow-up per main question, only if details are missing or the score is low."""
    if not state.turns:
        return False
    last = state.turns[-1]
    ev = last.evaluation
    if last.kind != "question" or not ev or ev.get("verdict") == "unassessed":
        return False
    return bool(ev.get("missing_details")) or float(ev.get("score", 0.0)) < FOLLOW_UP_THRESHOLD


def next_step(state: SessionState, candidates: list[Candidate], bullets: list[ResumeBulletRef]) -> NextStep:
    if state.turns and state.turns[-1].answer is None:
        raise ValueError("the latest question has not been answered yet")
    if needs_follow_up(state):
        return NextStep("follow_up")
    if state.main_questions >= state.target_questions:
        return NextStep("complete")
    return NextStep("question", select_question(state, candidates, bullets))


# ---------------- templates (offline mock and fallback) ----------------

def _pick(options: list[str], variant: int) -> str:
    return options[variant % len(options)]


def template_question(plan: QuestionPlan, role_title: str) -> str:
    """Deterministic wording for a plan. Used offline and when the model repeats itself."""
    name = plan.competency_name or "your core skills"
    role = role_title or "this role"
    if plan.category == "resume_deep_dive" and plan.bullet:
        probes = template_questions(plan.bullet) or ["Tell me more about this: what exactly did you do?"]
        return f"On your resume you wrote: \"{plan.bullet}\". {_pick(probes, plan.variant)}"
    if plan.category == "behavioral":
        return _pick([
            f"Tell me about a time you had to demonstrate {name}. What was the situation, what did you do, and what was the result?",
            f"Describe a situation where {name} was tested and things did not go to plan. How did you handle it?",
            f"Give an example of a time you used {name} to influence an outcome. What would you do differently now?",
        ], plan.variant)
    if plan.category == "case":
        return _pick([
            f"Imagine you join as {role} and the team asks you to solve a problem that hinges on {name}. How would you structure your approach, and what would you need to know first?",
            f"A key metric has dropped 15% this quarter and {name} is likely involved. Walk me through how you would diagnose it and what you would recommend.",
        ], plan.variant)
    if plan.category == "role_specific":
        return _pick([
            f"Why does {name} matter in the {role} role, and how would you apply it in your first 90 days?",
            f"What does good {name} look like in the {role} role, and where have you seen it done well or badly?",
        ], plan.variant)
    return _pick([
        f"How would you explain {name} to a colleague, and where have you applied it in practice?",
        f"Walk me through how you would use {name} to solve a typical problem in the {role} role. What trade-offs would you weigh?",
        f"What are the common pitfalls with {name}, and how do you avoid them?",
    ], plan.variant)


# ---------------- grading ----------------

def rubric_for(category: str) -> list[dict]:
    return RUBRICS.get(category, RUBRICS["technical"])


def band_verdict(score: float) -> str:
    for threshold, label in VERDICT_BANDS:
        if score >= threshold:
            return label
    return "needs_work"


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _drop_invented_numbers(items: list[str], allowed_text: str) -> list[str]:
    """Remove feedback items that cite figures the candidate never gave (no fabricated facts)."""
    allowed = set(_NUMBER_RE.findall(allowed_text))
    return [i for i in items if set(_NUMBER_RE.findall(i)) <= allowed]


def _clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [re.sub(r"\s+", " ", v).strip()[:300] for v in value if isinstance(v, str) and v.strip()]
    return list(dict.fromkeys(out))[:MAX_LIST_ITEMS]


def unassessed_evaluation(category: str, message: str) -> dict:
    return {
        "verdict": "unassessed", "score": 0.0,
        "criteria": [{**r, "status": "missing", "evidence": ""} for r in rubric_for(category)],
        "star": {k: False for k in STAR_KEYS} if category == "behavioral" else None,
        "strengths": [], "improvements": [], "missing_details": [], "feedback": message,
    }


def _star(criteria: list[dict]) -> dict:
    present = {c["criterion"].split(":", 1)[0].strip().lower(): c["status"] != "missing" for c in criteria}
    return {k: present.get(k, False) for k in STAR_KEYS}


def normalize_evaluation(raw: object, category: str, question: str, answer: str) -> dict:
    """Validated `Evaluation`: score recomputed from criteria, verdict banded, lists sanitised."""
    raw = raw if isinstance(raw, dict) else {}
    rubric = rubric_for(category)
    grade = normalize_rubric_grade(raw, rubric)
    if grade.verdict == "unassessed":
        return unassessed_evaluation(category, grade.feedback or "Could not evaluate this answer. Please retry.")
    allowed = f"{question} {answer}"
    return {
        "verdict": band_verdict(grade.score),
        "score": grade.score,
        "criteria": grade.criteria,
        "star": _star(grade.criteria) if category == "behavioral" else None,
        "strengths": _drop_invented_numbers(_clean_list(raw.get("strengths")), allowed),
        "improvements": _drop_invented_numbers(_clean_list(raw.get("improvements")), allowed),
        "missing_details": _drop_invented_numbers(_clean_list(raw.get("missing_details")), allowed),
        "feedback": str(raw.get("feedback", "")).strip()[:2000],
    }


# ---------------- summary ----------------

def _evaluated(turns: list[TurnState]) -> list[TurnState]:
    return [t for t in turns if t.evaluation and t.evaluation.get("verdict") != "unassessed"]


def build_summary(turns: list[TurnState]) -> dict:
    """Deterministic session summary from evaluated turns only."""
    done = _evaluated(turns)
    if not done:
        return {"overall": "No answers were evaluated in this session, so there is nothing to summarise yet.",
                "by_competency": [], "top_improvements": [], "suggested_drills": []}

    groups: dict[str, list[float]] = {}
    names: dict[str, str] = {}
    for t in done:
        if t.competency_id:
            groups.setdefault(t.competency_id, []).append(float(t.evaluation["score"]))
            names[t.competency_id] = t.competency_name or t.competency_id
    by_comp = sorted(
        ({"competency_id": cid, "name": names[cid], "score": round(sum(s) / len(s), 3), "attempts": len(s)} for cid, s in groups.items()),
        key=lambda r: (r["score"], r["name"].lower()),
    )

    improvements = Counter(i for t in done for i in t.evaluation.get("improvements", []))
    missed = Counter(c["criterion"] for t in done for c in t.evaluation.get("criteria", []) if c.get("status") == "missing")
    top = [i for i, _ in improvements.most_common(3)]
    top += [f"Work on: {c}" for c, _ in missed.most_common(3 - len(top))] if len(top) < 3 else []

    drills = [f"Drill {r['name']}: answer two more questions and aim for a concrete example with numbers." for r in by_comp if r["score"] < FOLLOW_UP_THRESHOLD][:3]
    if any(t.category == "behavioral" and not (t.evaluation.get("star") or {}).get("result") for t in done):
        drills.append("Rewrite one behavioral story so the result is concrete and measurable.")

    mean = sum(float(t.evaluation["score"]) for t in done) / len(done)
    strongest = max(by_comp, key=lambda r: r["score"])["name"] if by_comp else None
    overall = f"{band_verdict(mean).replace('_', ' ').capitalize()} overall: average {mean:.0%} across {len(done)} evaluated answer(s)."
    if strongest:
        overall += f" Strongest area: {strongest}."
    if by_comp and by_comp[0]["score"] < FOLLOW_UP_THRESHOLD:
        overall += f" Focus next on {by_comp[0]['name']}."
    return {"overall": overall, "by_competency": by_comp, "top_improvements": top, "suggested_drills": drills}
