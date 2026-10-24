"""Mock-interview use cases: ask, grade, follow up, summarise (PRD §7.5).

`core.interview_engine` decides *what* happens next; this module turns those
decisions into model calls and validated results. All functions mutate a
plain `SessionState`, which the router maps to and from database rows.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..ai import prompts_interview as P
from ..ai.gateway import Gateway, Request
from ..core.interview_engine import (
    Candidate,
    QuestionPlan,
    ResumeBulletRef,
    SessionState,
    TurnState,
    build_summary,
    next_step,
    normalize_evaluation,
    rubric_for,
    select_question,
    template_question,
    unassessed_evaluation,
)
from ..core.interview_matrix import SkillResult
from ..core.interview_parse import resume_bullets
from ..core.text import jaccard, tokenize

MIN_ANSWER_WORDS = 3
MAX_ANSWER_CHARS = 8000
REPEAT_SIMILARITY = 0.8


@dataclass(frozen=True)
class InterviewContext:
    """Prep data the interviewer draws on."""
    role_title: str
    candidates: list[Candidate]
    bullets: list[ResumeBulletRef]


def build_context(role_title: str, skills: list[SkillResult], job: dict, resume: dict) -> InterviewContext:
    quotes = {c["id"]: c.get("evidence_quote", "") for c in job.get("competencies") or []}
    candidates = [
        Candidate(s.competency_id, s.name, s.category, s.effective_priority, s.gap_type,
                  tuple(e["text"] for e in s.resume_evidence), quotes.get(s.competency_id, ""))
        for s in skills
    ]
    linked: dict[str, SkillResult] = {}
    for s in skills:
        for e in s.resume_evidence:
            linked.setdefault(e["bullet_id"], s)
    bullets = [
        ResumeBulletRef(b["id"], b["text"], b["role_title"],
                        linked[b["id"]].competency_id if b["id"] in linked else None,
                        linked[b["id"]].name if b["id"] in linked else None)
        for b in resume_bullets(resume)
    ]
    return InterviewContext(role_title, candidates, bullets)


def _clean_question(raw: object) -> str:
    if not isinstance(raw, dict) or not isinstance(raw.get("question"), str):
        raise ValueError("reply must be {'question': '...'}")
    q = re.sub(r"\s+", " ", raw["question"]).strip()
    if len(q) < 10:
        raise ValueError("question too short")
    return q[:800]


def _is_repeat(question: str, state: SessionState) -> bool:
    toks = set(tokenize(question))
    return any(jaccard(toks, set(tokenize(t.question))) >= REPEAT_SIMILARITY for t in state.turns)


def _ask(gw: Gateway, ctx: InterviewContext, state: SessionState, plan: QuestionPlan) -> TurnState:
    plan_dict = asdict(plan)
    question = gw.complete_json(
        Request(task="interview_question", system=P.QUESTION_SYSTEM,
                user=P.question_user(ctx.role_title, plan_dict, [t.question for t in state.turns]),
                tier="main", max_tokens=400, temperature=0.6,
                context={"plan": plan_dict, "role_title": ctx.role_title}),
        validate=_clean_question,
    )
    if _is_repeat(question, state):
        question = template_question(plan, ctx.role_title)  # deterministic, varied by plan.variant
    return TurnState("question", plan.category, question, plan.competency_id, plan.competency_name)


def start_session(gw: Gateway, ctx: InterviewContext, focus: str, target_questions: int) -> SessionState:
    """New session with its first question already asked."""
    state = SessionState(focus, target_questions)
    state.turns.append(_ask(gw, ctx, state, select_question(state, ctx.candidates, ctx.bullets)))
    return state


def _grade(gw: Gateway, turn: TurnState, answer: str) -> dict:
    if len(answer.split()) < MIN_ANSWER_WORDS:
        return unassessed_evaluation(turn.category, "The answer was too short to evaluate. Try answering in a few full sentences.")
    rubric = rubric_for(turn.category)
    raw = gw.complete_json(Request(
        task="interview_grade", system=P.GRADE_SYSTEM,
        user=P.grade_user(turn.category, turn.question, rubric, answer, turn.competency_name),
        tier="main", max_tokens=1500, temperature=0.0,
        context={"answer": answer, "rubric": rubric, "category": turn.category,
                 "question": turn.question, "competency": turn.competency_name},
    ))
    return normalize_evaluation(raw, turn.category, turn.question, answer)


def _follow_up(gw: Gateway, main: TurnState) -> TurnState:
    ev = main.evaluation or {}
    missing_criteria = [c["criterion"] for c in ev.get("criteria", []) if c.get("status") != "met"]
    question = gw.complete_json(
        Request(task="interview_follow_up", system=P.FOLLOW_UP_SYSTEM,
                user=P.follow_up_user(main.question, main.answer or "", ev),
                tier="main", max_tokens=300, temperature=0.4,
                context={"missing_details": ev.get("missing_details", []), "missing_criteria": missing_criteria,
                         "question": main.question}),
        validate=_clean_question,
    )
    return TurnState("follow_up", main.category, question, main.competency_id, main.competency_name)


def answer_turn(gw: Gateway, ctx: InterviewContext, state: SessionState, answer: str) -> tuple[TurnState, TurnState | None]:
    """Grade the latest turn, then append a follow-up or the next question, or finish.

    Returns (graded turn, newly asked turn or None when the session completed).
    The caller must persist `state.turns[-1]` changes and any appended turn.
    """
    if not state.turns or state.turns[-1].answer is not None:
        raise ValueError("There is no open question to answer in this session.")
    turn = state.turns[-1]
    turn.answer = answer.strip()[:MAX_ANSWER_CHARS]
    turn.evaluation = _grade(gw, turn, turn.answer)

    step = next_step(state, ctx.candidates, ctx.bullets)
    if step.action == "complete":
        return turn, None
    asked = _follow_up(gw, turn) if step.action == "follow_up" else _ask(gw, ctx, state, step.plan)
    state.turns.append(asked)
    return turn, asked


def summarize(state: SessionState) -> dict:
    return build_summary(state.turns)
