"""Prep plan and readiness dimensions (PRD §7.3, §7.5).

Deterministic: the plan is derived from the matrix, and readiness from counted
evidence. There is deliberately no single overall readiness percentage: one
number hides *why* someone is or isn't ready and invites false confidence.
Each dimension reports its own level, how much evidence backs it, and a
plain-language explanation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .interview_matrix import PRIORITY_ORDER, SkillResult

MAX_PLAN_ITEMS = 12
MINUTES = {"learn": 45, "practice": 30, "drill": 20, "story": 25, "mock_interview": 30}
KNOWLEDGE_CATEGORIES = ("technical", "domain", "tool")
STORY_CATEGORIES = ("behavioral", "leadership", "communication")
STRONG_SCORE, DEVELOPING_SCORE = 0.75, 0.5
MIN_READINESS_EVIDENCE = 2


# ---------------- plan ----------------

def _plan_activities(skill: SkillResult) -> list[tuple[str, str, str]]:
    """(activity, title, reason) steps for one skill, keyed by its gap type."""
    n, gap = skill.name, skill.gap_type
    if gap == "knowledge_gap":
        return [
            ("learn", f"Learn: {n}", f"Quiz results show {n} is not yet solid, and the role rates it {skill.jd_importance}."),
            ("practice", f"Practise applying {n}", "Close the loop with an applied question after studying."),
        ]
    if gap == "application_gap":
        kind = "drill" if skill.category in ("tool", "technical") else "practice"
        return [(kind, f"{'Drill' if kind == 'drill' else 'Practise'}: {n} on realistic problems",
                 "You know the concepts, but applied answers are still inconsistent.")]
    if gap in ("evidence_gap", "communication_gap"):
        why = ("Your mock answers did not yet show this clearly." if gap == "communication_gap"
               else "The role needs it, but your resume gives little concrete evidence.")
        title = (f"Prepare a concrete example of using {n}" if skill.category in KNOWLEDGE_CATEGORIES
                 else f"Prepare a STAR story for {n}")
        steps = [("story", title, why)]
        if gap == "evidence_gap" and skill.resume_strength == "none" and skill.category in KNOWLEDGE_CATEGORIES:
            steps.append(("learn", f"Refresh {n}", "With no resume evidence, be ready to show understanding instead."))
        return steps
    if gap == "unverified":
        kind = "story" if skill.category in STORY_CATEGORIES else "practice"
        return [(kind, f"Verify {n}: {'rehearse your example' if kind == 'story' else 'answer an applied question'}",
                 "Your resume claims it, but nothing has tested it yet.")]
    if gap == "stretch":
        return [("learn", f"Learn the basics of {n}", "A stretch area: aim to discuss it honestly, not to master it.")]
    return []


def build_plan(skills: list[SkillResult]) -> list[dict]:
    """Ordered prep steps, highest effective priority first, capped, ending with a mock interview."""
    ordered = sorted(skills, key=lambda s: (PRIORITY_ORDER[s.effective_priority], -s.priority_factors.get("importance", 0)))
    items: list[dict] = []
    for skill in ordered:
        if skill.effective_priority == "low" and items:
            continue  # low-priority gaps are shown in the matrix but not scheduled
        for activity, title, reason in _plan_activities(skill):
            if len(items) >= MAX_PLAN_ITEMS - 1:
                break
            items.append({
                "id": f"p{len(items) + 1}", "competency_id": skill.competency_id, "title": title,
                "activity": activity, "estimated_minutes": MINUTES[activity], "reason": reason,
            })
    items.append({
        "id": f"p{len(items) + 1}", "competency_id": None, "title": "Full mock interview",
        "activity": "mock_interview", "estimated_minutes": MINUTES["mock_interview"],
        "reason": "Rehearse under realistic conditions and get rubric feedback on every answer.",
    })
    return items


# ---------------- readiness ----------------

@dataclass(frozen=True)
class TurnScore:
    """An evaluated mock-interview answer, reduced to what readiness needs."""
    category: str
    score: float


def _level(scores: list[float]) -> str:
    if len(scores) < MIN_READINESS_EVIDENCE:
        return "unverified"
    mean = sum(scores) / len(scores)
    return "strong" if mean >= STRONG_SCORE else "developing" if mean >= DEVELOPING_SCORE else "weak"


def _dim(dimension: str, scores: list[float], what: str, none_hint: str) -> dict:
    level = _level(scores)
    if not scores:
        text = f"No evidence yet. {none_hint}"
    elif level == "unverified":
        text = f"Only {len(scores)} {what} so far; need at least {MIN_READINESS_EVIDENCE} before rating. {none_hint}"
    else:
        text = f"{level.capitalize()}: average {sum(scores) / len(scores):.0%} across {len(scores)} {what}."
    return {"dimension": dimension, "level": level, "evidence_count": len(scores), "explanation": text}


_LEVEL_SCORE = {"strong": 0.9, "developing": 0.65, "weak": 0.3}


def _resume_evidence_dim(skills: list[SkillResult]) -> dict:
    """Share of important competencies backed by a strong resume bullet."""
    important = [s for s in skills if s.jd_importance in ("critical", "high")] or skills
    backed = sum(1 for s in important if s.resume_strength == "strong")
    count = sum(len(s.resume_evidence) for s in important)
    if not important:
        return {"dimension": "resume_evidence", "level": "unverified", "evidence_count": 0,
                "explanation": "No competencies parsed from the job description yet."}
    share = backed / len(important)
    level = "strong" if share >= 0.75 else "developing" if share >= 0.4 else "weak"
    return {"dimension": "resume_evidence", "level": level, "evidence_count": count,
            "explanation": f"{backed} of {len(important)} key requirements have a strong resume bullet behind them."}


def build_readiness(skills: list[SkillResult], turns: list[TurnScore]) -> list[dict]:
    """Five dimensions, each from its own evidence; quiz levels feed role knowledge."""
    knowledge = [_LEVEL_SCORE[s.assessed_level] for s in skills
                 if s.category in KNOWLEDGE_CATEGORIES and s.assessed_level in _LEVEL_SCORE]
    knowledge += [t.score for t in turns if t.category in ("technical", "role_specific")]
    applied = [t.score for t in turns if t.category in ("case", "technical")]
    behavioral = [t.score for t in turns if t.category in ("behavioral", "resume_deep_dive")]
    communication = [t.score for t in turns]
    return [
        _dim("role_knowledge", knowledge, "assessed skills and technical answers",
             "Take quizzes on the role's technical skills or a technical mock interview."),
        _dim("applied_problem_solving", applied, "case or technical answers",
             "Run a mock interview with case or technical focus."),
        _resume_evidence_dim(skills),
        _dim("behavioral_examples", behavioral, "behavioral or resume answers",
             "Run a behavioral or resume mock interview to test your stories."),
        _dim("communication", communication, "evaluated interview answers",
             "Answer mock interview questions; clarity and structure are scored on every answer."),
    ]
