"""Interview-prep use cases: parsing, skill matrix, plan, readiness, deep dives (PRD §7.1-7.4).

Functions take plain data and a Gateway and contain no web or database code,
so the whole pipeline runs under the offline mock in tests. The model is used
for extraction and match judgement only; every judgement shown to the user is
computed by `app.core.interview_*`.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ..ai import prompts_interview as P
from ..ai.gateway import BudgetExceeded, Gateway, ModelError, Request
from ..core.interview_deepdive import analyse_claim, merge_questions, template_questions
from ..core.interview_matrix import (
    UNASSESSED,
    AssessmentSignal,
    InterviewSignal,
    SkillResult,
    assessment_signal,
    build_skill,
    days_until,
    sort_key,
    validate_judgements,
)
from ..core.interview_parse import ParseOutcome, resume_bullets, validate_job, validate_resume
from ..core.interview_plan import TurnScore
from ..core.mastery import AttemptEvidence
from .learning import ChunkData, retrieve

log = logging.getLogger("mindmesh.interview")

LINKED_SOURCES_PER_SKILL = 2
MAX_DEEP_DIVE_BULLETS = 12

Judgements = dict[str, list[tuple[str, str]]]


# ---------------- parsing ----------------

def parse_resume(gw: Gateway, text: str) -> ParseOutcome:
    """Extract `ResumeParsed`; anything not verbatim in `text` is dropped with a warning."""
    return gw.complete_json(
        Request(task="resume_parse", system=P.RESUME_PARSE_SYSTEM, user=P.resume_parse_user(text),
                tier="fast", max_tokens=4000, temperature=0.0, context={"text": text}),
        validate=lambda raw: validate_resume(raw, text),
    )


def parse_job(gw: Gateway, text: str) -> ParseOutcome:
    """Extract `JobParsed`; competencies whose quote is not in the JD are dropped."""
    return gw.complete_json(
        Request(task="jd_parse", system=P.JD_PARSE_SYSTEM, user=P.jd_parse_user(text),
                tier="fast", max_tokens=3000, temperature=0.0, context={"text": text}),
        validate=lambda raw: validate_job(raw, text),
    )


# ---------------- matching ----------------

def match_skills(gw: Gateway, job: dict, resume: dict) -> Judgements:
    """Ask the model which bullets evidence which competency; unknown ids are discarded."""
    competencies = job.get("competencies") or []
    bullets = resume_bullets(resume)
    if not competencies or not bullets:
        return {}
    comp_ids = {c["id"] for c in competencies}
    bullet_ids = {b["id"] for b in bullets}
    return gw.complete_json(
        Request(task="skill_match", system=P.SKILL_MATCH_SYSTEM, user=P.skill_match_user(competencies, bullets),
                tier="fast", max_tokens=3000, temperature=0.0,
                context={"competencies": competencies, "bullets": bullets}),
        validate=lambda raw: validate_judgements(raw, comp_ids, bullet_ids),
    )


@dataclass(frozen=True)
class MatrixInputs:
    """Everything the deterministic scorer needs besides the model's judgements."""
    attempts_by_concept: dict[str, list[AttemptEvidence]]
    interview_by_competency: dict[str, InterviewSignal]
    interview_date: date | None
    today: date
    overrides: dict[str, dict]
    now: datetime | None = None


def score_matrix(job: dict, resume: dict, judgements: Judgements, inputs: MatrixInputs) -> list[SkillResult]:
    """One row per JD competency, sorted for display. Pure: safe to re-run at any time."""
    bullets_by_id = {b["id"]: b for b in resume_bullets(resume)}
    skills_list = resume.get("skills") or []
    days_left = days_until(inputs.interview_date, inputs.today)
    rows = []
    for comp in job.get("competencies") or []:
        assessed: AssessmentSignal = (
            assessment_signal(comp["name"], inputs.attempts_by_concept, inputs.now) if inputs.attempts_by_concept else UNASSESSED
        )
        rows.append(build_skill(
            comp, judgements.get(comp["id"], []), bullets_by_id, skills_list, assessed,
            inputs.interview_by_competency.get(comp["id"]), days_left, inputs.overrides.get(comp["id"]),
        ))
    return sorted(rows, key=sort_key)


def link_sources(skills: list[SkillResult], job: dict, chunks: Sequence[ChunkData]) -> None:
    """Attach the top study chunks from the user's selected documents to each skill (in place)."""
    if not chunks:
        for s in skills:
            s.linked_chunk_ids = []
        return
    quotes = {c["id"]: c.get("evidence_quote", "") for c in job.get("competencies") or []}
    for s in skills:
        hits = retrieve(chunks, s.name, k=LINKED_SOURCES_PER_SKILL) or retrieve(
            chunks, f"{s.name} {quotes.get(s.competency_id, '')}", k=LINKED_SOURCES_PER_SKILL
        )
        s.linked_chunk_ids = [h.chunk_id for h in hits]


def interview_signals(turns: Sequence[tuple[str | None, dict | None]]) -> dict[str, InterviewSignal]:
    """Mean score per competency over evaluated mock-interview turns (competency_id, evaluation)."""
    scores: dict[str, list[float]] = {}
    for cid, ev in turns:
        if cid and ev and ev.get("verdict") != "unassessed":
            scores.setdefault(cid, []).append(float(ev.get("score", 0.0)))
    return {cid: InterviewSignal(len(v), round(sum(v) / len(v), 3)) for cid, v in scores.items()}


def turn_scores(turns: Sequence[tuple[str, dict | None]]) -> list[TurnScore]:
    """(category, evaluation) pairs -> readiness inputs, skipping unassessed answers."""
    return [TurnScore(cat, float(ev["score"])) for cat, ev in turns if ev and ev.get("verdict") != "unassessed"]

# ---------------- deep dive ----------------

def deep_dive(gw: Gateway, resume: dict, role_title: str, generate: bool = True) -> list[dict]:
    """Probing questions per resume claim: deterministic templates, plus model extras when available.

    Model generation is best-effort: if the budget is exhausted or the model is
    down, the template questions alone are still a complete answer.
    """
    bullets = [b for b in resume_bullets(resume) if analyse_claim(b["text"]).probeable][:MAX_DEEP_DIVE_BULLETS]
    extra: dict[str, list[str]] = {}
    if generate and bullets:
        try:
            extra = gw.complete_json(
                Request(task="interview_deep_dive", system=P.DEEP_DIVE_SYSTEM, user=P.deep_dive_user(role_title, bullets),
                        tier="fast", max_tokens=2500, temperature=0.3, context={"bullets": bullets}),
                validate=lambda raw: _validate_deep_dive(raw, {b["id"] for b in bullets}),
            )
        except (BudgetExceeded, ModelError, ValueError) as exc:
            log.info("deep-dive generation skipped: %s", type(exc).__name__)
    return [
        {"bullet_id": b["id"], "bullet": b["text"], "questions": merge_questions(template_questions(b["text"]), extra.get(b["id"], []))}
        for b in bullets
    ]


def _validate_deep_dive(raw: object, ids: set[str]) -> dict[str, list[str]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ValueError("deep dive reply must be {'items': [...]}")
    out: dict[str, list[str]] = {}
    for item in raw["items"]:
        if isinstance(item, dict) and item.get("bullet_id") in ids:
            qs = [q.strip()[:300] for q in item.get("questions") or [] if isinstance(q, str) and len(q.strip()) > 10]
            out[item["bullet_id"]] = qs[:3]
    return out
