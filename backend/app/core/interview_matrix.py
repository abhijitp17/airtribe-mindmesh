"""Role-skill matrix: evidence, gap categories and priorities (PRD §7.2, §7.3).

The model's only job in matching is to say which resume bullets are evidence
for which competency, and how strongly. Everything a user sees as a judgement
(gap type, priority, confidence, recommended action) is computed here by
transparent rules so it is explainable ("why this priority?") and testable.

Two honesty rules from the PRD are enforced structurally:

* A keyword is never proof: a skill that appears only in the resume's skills
  list gives `partial` evidence at most, so it can never be classed `strong`.
* Absence of a quiz result is not weakness: without assessment evidence a
  skill is `unverified` (or an evidence gap), never `weak`/`knowledge_gap`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .mastery import AttemptEvidence, MasteryEstimate, estimate
from .text import tokenize

IMPORTANCE_WEIGHT = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
IMPORTANCE_ORDER = PRIORITY_ORDER

# How bad each gap is if left alone (0..1). "strong" still gets a little weight so
# a critical skill is rehearsed before the interview rather than ignored.
GAP_SEVERITY = {
    "knowledge_gap": 1.0,
    "application_gap": 0.8,
    "evidence_gap": 0.75,
    "communication_gap": 0.7,
    "stretch": 0.5,
    "unverified": 0.4,
    "strong": 0.1,
}
EVIDENCE_GAP_PARTIAL_SEVERITY = 0.55  # listed or loosely shown is less severe than absent
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.75, "low": 0.5}
# Typical days of focused prep to close each gap; drives feasibility.
EFFORT_DAYS = {
    "knowledge_gap": 5, "application_gap": 3, "evidence_gap": 1, "communication_gap": 1,
    "stretch": 10, "unverified": 1, "strong": 1,
}
DEFAULT_DAYS_LEFT = 14  # assumed runway when the user has not set an interview date
URGENCY_HORIZON_DAYS = 30
# Calibrated so that, with no interview date set: a critical requirement with no
# evidence is critical, a medium-importance knowledge gap is high, a claimed but
# untested high-importance skill is medium, and a strong skill is low.
PRIORITY_BANDS = ((0.4, "critical"), (0.22, "high"), (0.1, "medium"))

INTERVIEW_WEAK, INTERVIEW_STRONG = 0.6, 0.75
APPLIED_WEAK = 0.6
MAX_EVIDENCE_PER_SKILL = 5
# Words that make two different skill names look alike without meaning the same thing.
_GENERIC_TOKENS = frozenset(tokenize(
    "management manage skill skills experience knowledge ability strong solid basic advanced "
    "understanding concept concepts principle principles fundamentals tool tools method methods "
    "work working general applied practical"
))


# ---------------- inputs ----------------

@dataclass(frozen=True)
class AssessmentSignal:
    """Quiz evidence for one competency, derived from the learner's mastery data."""
    level: str  # strong | developing | weak | unverified
    estimate: float
    evidence_count: int
    explanation: str
    applied_count: int = 0
    applied_mean: float | None = None


UNASSESSED = AssessmentSignal("unverified", 0.0, 0, "No quiz answers on this skill yet.")


@dataclass(frozen=True)
class InterviewSignal:
    """Mock-interview performance on one competency (scores of evaluated turns)."""
    attempts: int
    mean: float


@dataclass
class SkillResult:
    competency_id: str
    name: str
    category: str
    jd_importance: str
    resume_strength: str
    resume_evidence: list[dict]
    assessed_level: str
    assessed_explanation: str
    confidence: str
    gap_type: str
    priority: str
    priority_factors: dict[str, float]
    recommended_action: str
    linked_chunk_ids: list[str] = field(default_factory=list)
    user_override: dict | None = None

    @property
    def effective_priority(self) -> str:
        """The user's override wins for ordering and planning; the computed value stays visible."""
        return (self.user_override or {}).get("priority") or self.priority


# ---------------- match judgements ----------------

def validate_judgements(raw: Any, competency_ids: set[str], bullet_ids: set[str]) -> dict[str, list[tuple[str, str]]]:
    """Keep only (bullet_id, strength) pairs that reference real ids.

    Unknown ids are dropped silently: the model cannot invent evidence.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("matches"), list):
        raise ValueError("skill_match reply must be {'matches': [...]}")
    out: dict[str, list[tuple[str, str]]] = {}
    for m in raw["matches"]:
        if not isinstance(m, dict) or m.get("competency_id") not in competency_ids:
            continue
        pairs = out.setdefault(m["competency_id"], [])
        seen = {b for b, _ in pairs}
        for e in m.get("evidence") or []:
            if not isinstance(e, dict):
                continue
            bid, strength = e.get("bullet_id"), str(e.get("strength", "")).lower()
            if bid in bullet_ids and bid not in seen and strength in ("strong", "partial"):
                pairs.append((bid, strength))
                seen.add(bid)
        pairs.sort(key=lambda p: p[1] != "strong")
        del pairs[MAX_EVIDENCE_PER_SKILL:]
    return out


def skill_listed(name: str, skills: list[str]) -> bool:
    """True when the competency appears in the resume's skills list (keyword only)."""
    target = set(tokenize(name)) - _GENERIC_TOKENS or set(tokenize(name))
    if not target:
        return False
    return any(target <= set(tokenize(s)) or set(tokenize(s)) - _GENERIC_TOKENS == target for s in skills if tokenize(s))


def resume_strength(pairs: list[tuple[str, str]], listed: bool) -> str:
    """Strong needs a bullet the matcher rated strong; a skills-list mention caps at partial."""
    if any(s == "strong" for _, s in pairs):
        return "strong"
    if pairs or listed:
        return "partial"
    return "none"


# ---------------- assessment (quiz mastery) ----------------

def _content_tokens(text: str) -> set[str]:
    toks = set(tokenize(text))
    return toks - _GENERIC_TOKENS or toks


def concept_matches(competency: str, concept: str) -> bool:
    """Case-insensitive token overlap, ignoring generic words, covering half of both names.

    "SQL" matches "SQL joins"; "Stakeholder management" does not match "Project management".
    """
    a, b = _content_tokens(competency), _content_tokens(concept)
    if not a or not b:
        return False
    shared = len(a & b)
    return shared / len(a) >= 0.5 and shared / len(b) >= 0.5


def assessment_signal(
    competency: str, attempts_by_concept: dict[str, list[AttemptEvidence]], now=None
) -> AssessmentSignal:
    """Pool quiz attempts from every matching concept and reuse the mastery model."""
    matched = sorted(c for c in attempts_by_concept if concept_matches(competency, c))
    attempts = [a for c in matched for a in attempts_by_concept[c]]
    if not attempts:
        return UNASSESSED
    m: MasteryEstimate = estimate(competency, attempts, now)
    applied = [a.score for a in attempts if a.qtype == "applied"]
    source = f" (from quiz concepts: {', '.join(matched[:3])})"
    return AssessmentSignal(
        m.level, m.estimate, m.evidence_count, m.explanation.rstrip(".") + source + ".",
        len(applied), round(sum(applied) / len(applied), 3) if applied else None,
    )


# ---------------- classification ----------------

def confidence(strength: str, evidence_refs: int, assessed: AssessmentSignal, interview: InterviewSignal | None) -> str:
    """How much independent evidence backs our picture of this skill.

    Quiz and interview results are observed performance and count double;
    resume bullets are self-reported claims.
    """
    points = 0
    if assessed.level != "unverified":
        points += 2
    if interview and interview.attempts >= 2:
        points += 2
    elif interview:
        points += 1
    if strength == "strong":
        points += 1
    if evidence_refs >= 2:
        points += 1
    return "high" if points >= 3 else "medium" if points >= 1 else "low"


def gap_type(
    strength: str, assessed: AssessmentSignal, interview: InterviewSignal | None, importance: str
) -> str:
    """PRD §7.2 gap categories as an ordered decision table (first match wins)."""
    if assessed.level == "weak":
        return "knowledge_gap"
    if interview and interview.mean < INTERVIEW_WEAK and strength != "none":
        return "communication_gap"  # has the experience but did not convey it
    applied_weak = assessed.applied_mean is not None and assessed.applied_mean < APPLIED_WEAK
    if assessed.level == "developing" or (assessed.level == "strong" and applied_weak):
        return "application_gap"
    if assessed.level == "strong":
        return "strong" if strength == "strong" else "evidence_gap"
    # No quiz evidence below this point: never a knowledge gap.
    if strength == "strong":
        if interview and interview.attempts >= 2 and interview.mean >= INTERVIEW_STRONG:
            return "strong"
        return "unverified"
    if strength == "partial":
        return "evidence_gap"
    return "evidence_gap" if importance in ("critical", "high") else "stretch"


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def days_until(interview_date: date | None, today: date) -> int | None:
    return None if interview_date is None else (interview_date - today).days


def urgency(days_left: int | None) -> float:
    """1.0 at (or past) the interview, falling linearly to 0.1 at 30+ days; 0.5 when unknown."""
    if days_left is None:
        return 0.5
    return round(_clamp(1 - days_left / URGENCY_HORIZON_DAYS, 0.1, 1.0), 3)


def feasibility(gap: str, days_left: int | None) -> float:
    """Can this gap realistically be closed before the interview? Big gaps on short notice score low."""
    runway = DEFAULT_DAYS_LEFT if days_left is None else max(0, days_left)
    return round(_clamp(runway / EFFORT_DAYS[gap], 0.2, 1.0), 3)


def priority_factors(gap: str, strength: str, importance: str, conf: str, days_left: int | None) -> dict[str, float]:
    severity = EVIDENCE_GAP_PARTIAL_SEVERITY if gap == "evidence_gap" and strength == "partial" else GAP_SEVERITY[gap]
    return {
        "importance": IMPORTANCE_WEIGHT[importance],
        "gap_severity": severity,
        "evidence_confidence": CONFIDENCE_WEIGHT[conf],
        "urgency": urgency(days_left),
        "feasibility": feasibility(gap, days_left),
    }


def priority_score(f: dict[str, float]) -> float:
    """PRD §7.3 product. Importance and severity act fully; the other factors modulate by up to 2x.

    A raw five-way product collapses everything towards zero, which makes bands
    meaningless; modulating the secondary factors keeps the order monotone in
    every factor while leaving importance x severity as the main driver.
    """
    def mod(x: float) -> float:
        return 0.5 + 0.5 * x

    return f["importance"] * f["gap_severity"] * mod(f["evidence_confidence"]) * mod(f["urgency"]) * mod(f["feasibility"])


def band_priority(score: float) -> str:
    for threshold, label in PRIORITY_BANDS:
        if score >= threshold:
            return label
    return "low"


_ACTIONS = {
    "knowledge_gap": "Learn the fundamentals of {name} from your materials, then retake a short quiz to confirm.",
    "application_gap": "You know the basics of {name}; practise applying it to realistic problems and timed drills.",
    "evidence_gap": "Prepare a specific STAR example that shows {name}. If you have none, take a quiz to check your understanding and be ready to explain how you would apply it.",
    "communication_gap": "Your resume shows {name}, but your mock answers did not convey it. Rehearse a clear, structured answer with your real numbers.",
    "unverified": "Your resume claims {name}, but it has not been tested. Run a quick quiz or mock question to confirm you can explain it in depth.",
    "stretch": "{name} is a stretch for your background. Learn enough to discuss it honestly; prioritise core requirements first.",
    "strong": "{name} looks solid. Keep one concise example ready and review it the day before.",
}


def recommended_action(gap: str, name: str) -> str:
    return _ACTIONS[gap].format(name=name)


# ---------------- assembly ----------------

def build_skill(
    competency: dict,
    pairs: list[tuple[str, str]],
    bullets_by_id: dict[str, dict],
    skills_list: list[str],
    assessed: AssessmentSignal,
    interview: InterviewSignal | None,
    days_left: int | None,
    override: dict | None = None,
) -> SkillResult:
    """Compute one matrix row from validated evidence; no model calls."""
    importance = competency["importance"] if competency.get("importance") in IMPORTANCE_WEIGHT else "medium"
    pairs = [(bid, s) for bid, s in pairs if bid in bullets_by_id]  # bullets may have been edited away
    strength = resume_strength(pairs, skill_listed(competency["name"], skills_list))
    # "strength" is stored with each reference so the matrix can be re-scored (new date,
    # new quiz evidence) without another model call; the API schema omits it.
    evidence = [
        {"bullet_id": bid, "text": bullets_by_id[bid]["text"], "role_title": bullets_by_id[bid]["role_title"], "strength": s}
        for bid, s in pairs
    ]
    conf = confidence(strength, len(evidence), assessed, interview)
    gap = gap_type(strength, assessed, interview, importance)
    factors = priority_factors(gap, strength, importance, conf, days_left)
    return SkillResult(
        competency_id=competency["id"], name=competency["name"], category=competency.get("category", "technical"),
        jd_importance=importance, resume_strength=strength, resume_evidence=evidence,
        assessed_level=assessed.level, assessed_explanation=assessed.explanation, confidence=conf,
        gap_type=gap, priority=band_priority(priority_score(factors)), priority_factors=factors,
        recommended_action=recommended_action(gap, competency["name"]), user_override=override,
    )


def sort_key(skill: SkillResult) -> tuple:
    """Contract order: priority (critical first), then JD importance, then name for stability."""
    return (PRIORITY_ORDER[skill.effective_priority], IMPORTANCE_ORDER[skill.jd_importance], skill.name.lower())


def skill_from_row(row: dict) -> SkillResult:
    """Rehydrate a stored matrix row (plain dict of SkillResult fields)."""
    return SkillResult(**{k: row[k] for k in SkillResult.__dataclass_fields__ if k in row})


def judgements_from_skills(skills: list[SkillResult]) -> dict[str, list[tuple[str, str]]]:
    """Recover the validated match judgements stored with each skill's evidence."""
    return {
        s.competency_id: [(e["bullet_id"], e.get("strength", "partial")) for e in s.resume_evidence]
        for s in skills
    }
