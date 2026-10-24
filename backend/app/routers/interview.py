"""Interview prep API (PRD §7, contract in docs/CONTRACTS.md §3).

A thin adapter: it loads owner-scoped rows, hands plain data to
`app.services.interview*`, and persists the results. No scoring or
selection logic lives here. Every lookup filters by `owner_id`, so other
users' resources are indistinguishable from missing ones (404).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from ..ai.gateway import BudgetExceeded, Gateway, ModelError
from ..clock import user_today
from ..core.interview_engine import RUBRIC_VERSION, SessionState, TurnState
from ..core.interview_matrix import SkillResult, judgements_from_skills, skill_from_row
from ..core.interview_parse import normalize_job_edit, normalize_resume_edit
from ..core.interview_plan import build_plan, build_readiness
from ..core.interview_text import InputError, UnsupportedFileType, extract_resume_file, prepare_text
from ..core.upload_safety import UploadRejected, scan
from ..core.jsonutil import JSONExtractionError
from ..core.mastery import AttemptEvidence
from ..db import get_db
from ..deps import current_user, gateway_for
from ..models import Attempt, Chunk, Document, Question, User
from ..models_interview import InterviewSession, InterviewTurn, JobProfile, ResumeProfile, RolePrep, SkillMatch
from ..schemas_interview import (
    ShareOut,
    StudyLinkOut,
    AnswerIn,
    DeepDiveItem,
    InterviewSessionOut,
    JobCreate,
    JobOut,
    JobUpdate,
    PrepCreate,
    PrepOut,
    PrepPatch,
    PrepSummary,
    ResumeOut,
    ResumeTextIn,
    ResumeUpdate,
    SessionCreate,
    SessionListItem,
    SkillMatchOut,
    SkillPatch,
)
from ..services import interview as svc
from ..services import interview_session as isvc
from ..services.learning import ChunkData
from ..services import analytics
from ..jobs import dispatch

log = logging.getLogger("mindmesh.interview")
router = APIRouter(prefix="/interview", tags=["interview"])

MAX_RESUME_BYTES = 10 * 1024 * 1024


# ---------- helpers ----------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ai_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI service is temporarily unavailable. Your data is safe; please retry.") from exc
    except (JSONExtractionError, ValueError) as exc:
        log.warning("unusable model output in %s: %s", getattr(fn, "__name__", fn), type(exc).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI returned an unusable result. Please retry.") from exc


def _owned(model, obj_id: str, user: User, db: Session, label: str):
    row = db.scalar(select(model).where(model.id == obj_id, model.owner_id == user.id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found")
    return row


def _ready_document_ids(ids: list[str], user: User, db: Session) -> list[str]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    docs = db.scalars(select(Document).where(Document.id.in_(ids), Document.owner_id == user.id)).all()
    if len(docs) != len(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more documents were not found.")
    busy = [d.filename for d in docs if d.status not in ("ready", "needs_attention")]
    if busy:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Still processing: {', '.join(busy)}")
    return ids


def _chunks(doc_ids: list[str], user: User, db: Session) -> list[ChunkData]:
    if not doc_ids:
        return []
    rows = db.scalars(
        select(Chunk).where(Chunk.document_id.in_(doc_ids), Chunk.owner_id == user.id).order_by(Chunk.document_id, Chunk.ordinal)
    ).all()
    return [ChunkData(c.id, c.text, c.page_start, c.page_end, c.section, c.document_id) for c in rows]


def _linked_sources(chunk_ids: set[str], user: User, db: Session) -> dict[str, dict]:
    if not chunk_ids:
        return {}
    rows = db.execute(
        select(Chunk.id, Chunk.document_id, Chunk.page_start, Chunk.page_end, Chunk.section, Document.title, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(chunk_ids), Chunk.owner_id == user.id)
    ).all()
    return {
        r[0]: {"chunk_id": r[0], "document_id": r[1], "page_start": r[2], "page_end": r[3], "section": r[4], "document_title": r[5] or r[6]}
        for r in rows
    }


def _attempts_by_concept(user: User, db: Session) -> dict[str, list[AttemptEvidence]]:
    """Same evidence the progress page uses: unflagged, assessed quiz attempts."""
    rows = db.execute(
        select(Attempt.score, Attempt.created_at, Question.concept, Question.qtype, Question.difficulty)
        .join(Question, Question.id == Attempt.question_id)
        .where(Attempt.owner_id == user.id, Question.flagged.is_(None), Attempt.verdict != "unassessed")
        .order_by(Attempt.created_at)
    ).all()
    out: dict[str, list[AttemptEvidence]] = defaultdict(list)
    for score, at, concept, qtype, difficulty in rows:
        out[concept].append(AttemptEvidence(score, qtype, difficulty, at))
    return dict(out)


def _prep_turns(prep: RolePrep, user: User, db: Session) -> list[tuple[str | None, str, dict | None]]:
    """(competency_id, category, evaluation) for every turn in this prep's sessions."""
    rows = db.execute(
        select(InterviewTurn.competency_id, InterviewTurn.category, InterviewTurn.evaluation)
        .join(InterviewSession, InterviewSession.id == InterviewTurn.session_id)
        .where(InterviewSession.prep_id == prep.id, InterviewTurn.owner_id == user.id)
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def _row_result(row: SkillMatch) -> SkillResult:
    return skill_from_row({c: getattr(row, c) for c in SkillResult.__dataclass_fields__ if hasattr(row, c)})


def _score(prep: RolePrep, job: JobProfile, resume: ResumeProfile, judgements: svc.Judgements, user: User, db: Session) -> list[SkillResult]:
    turns = _prep_turns(prep, user, db)
    inputs = svc.MatrixInputs(
        attempts_by_concept=_attempts_by_concept(user, db),
        interview_by_competency=svc.interview_signals([(cid, ev) for cid, _, ev in turns]),
        interview_date=prep.interview_date,
        today=user_today(),
        overrides={r.competency_id: r.user_override for r in prep.skills if r.user_override},
    )
    return svc.score_matrix(job.parsed, resume.parsed, judgements, inputs)


def _save_matrix(prep: RolePrep, results: list[SkillResult], user: User, db: Session) -> None:
    """Upsert rows by competency id so skill ids (and overrides) survive a recompute."""
    existing = {r.competency_id: r for r in prep.skills}
    keep: list[SkillMatch] = []
    for rank, res in enumerate(results):
        row = existing.pop(res.competency_id, None) or SkillMatch(owner_id=user.id, competency_id=res.competency_id)
        row.rank = rank
        for name in ("name", "category", "jd_importance", "resume_strength", "resume_evidence", "assessed_level",
                     "assessed_explanation", "confidence", "gap_type", "priority", "priority_factors",
                     "recommended_action", "linked_chunk_ids", "user_override"):
            setattr(row, name, getattr(res, name))
        keep.append(row)
    prep.skills = keep  # rows left in `existing` are orphans and are deleted
    prep.plan = build_plan(results)
    prep.updated_at = _now()


def _parents(prep: RolePrep, user: User, db: Session) -> tuple[JobProfile, ResumeProfile]:
    return _owned(JobProfile, prep.job_id, user, db, "Job"), _owned(ResumeProfile, prep.resume_id, user, db, "Resume")


def _rescore(prep: RolePrep, user: User, db: Session, relink: bool = False) -> None:
    """Deterministic re-score from stored judgements (no model call): new date, overrides, evidence."""
    job, resume = _parents(prep, user, db)
    stored = [_row_result(r) for r in prep.skills]
    results = _score(prep, job, resume, judgements_from_skills(stored), user, db)
    if relink:
        svc.link_sources(results, job.parsed, _chunks(prep.document_ids, user, db))
    else:
        links = {s.competency_id: s.linked_chunk_ids for s in stored}
        for r in results:
            r.linked_chunk_ids = links.get(r.competency_id, [])
    _save_matrix(prep, results, user, db)


def _skill_out(row: SkillMatch, sources: dict[str, dict]) -> SkillMatchOut:
    return SkillMatchOut.model_validate({
        "id": row.id, "competency_id": row.competency_id, "name": row.name, "category": row.category,
        "jd_importance": row.jd_importance, "resume_strength": row.resume_strength, "resume_evidence": row.resume_evidence,
        "assessed_level": row.assessed_level, "assessed_explanation": row.assessed_explanation,
        "confidence": row.confidence, "gap_type": row.gap_type, "priority": row.priority,
        "priority_factors": row.priority_factors, "recommended_action": row.recommended_action,
        "linked_sources": [sources[c] for c in row.linked_chunk_ids if c in sources],
        "user_override": row.user_override or None,
    })


def _prep_out(prep: RolePrep, user: User, db: Session) -> PrepOut:
    job, resume = _parents(prep, user, db)
    rows = sorted(prep.skills, key=lambda r: r.rank)
    # Readiness reflects the latest quiz attempts and interview answers even before a recompute.
    fresh = _score(prep, job, resume, judgements_from_skills([_row_result(r) for r in rows]), user, db)
    readiness = build_readiness(fresh, svc.turn_scores([(cat, ev) for _, cat, ev in _prep_turns(prep, user, db)]))
    sources = _linked_sources({c for r in rows for c in r.linked_chunk_ids}, user, db)
    return PrepOut(
        id=prep.id, resume_id=prep.resume_id, job_id=prep.job_id, role_title=job.role_title, company=job.company,
        interview_date=prep.interview_date, document_ids=prep.document_ids,
        skills=[_skill_out(r, sources) for r in rows], plan=prep.plan, readiness=readiness,
        created_at=prep.created_at, updated_at=prep.updated_at,
    )


# ---------- resumes ----------

def _store_resume(text: str, filename: str | None, warnings: list[str], user: User, db: Session, gw: Gateway) -> ResumeProfile:
    outcome = _ai_call(svc.parse_resume, gw, text)
    resume = ResumeProfile(
        owner_id=user.id, source_filename=filename, raw_text=text,
        parsed=outcome.parsed, warnings=warnings + outcome.warnings, user_confirmed=False,
    )
    db.add(resume)
    db.commit()
    return resume


def _resume_from_file(data: bytes, filename: str | None, user: User, db: Session, gw: Gateway) -> ResumeProfile:
    try:
        extracted = extract_resume_file(data, filename)
    except UnsupportedFileType as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except InputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    safe_name = (filename or "resume").replace("/", "_").replace("\\", "_")[:255]
    return _store_resume(extracted.text, safe_name, extracted.warnings, user, db, gw)


def _resume_from_text(text: str, user: User, db: Session, gw: Gateway) -> ResumeProfile:
    try:
        extracted = prepare_text(text, "resume")
    except InputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _store_resume(extracted.text, None, extracted.warnings, user, db, gw)


_RESUME_BODY_DOC = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {"schema": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}, "required": ["file"]}},
            "application/json": {"schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
        },
    }
}


@router.post("/resumes", response_model=ResumeOut, status_code=201, openapi_extra=_RESUME_BODY_DOC)
async def create_resume(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    """Multipart `file` (PDF/DOCX) or JSON `{text}`; the content type decides which."""
    ctype = request.headers.get("content-type", "").lower()
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Attach the resume as a form field named 'file'.")
        data = await upload.read(MAX_RESUME_BYTES + 1)
        if len(data) > MAX_RESUME_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Resume files must be under 10 MB.")
        try:
            await run_in_threadpool(scan, data)  # no-op unless UPLOAD_SCAN is configured
        except UploadRejected as exc:
            raise HTTPException(exc.status, exc.message) from exc
        return await run_in_threadpool(_resume_from_file, data, upload.filename, user, db, gw)
    if ctype.startswith("application/json"):
        try:
            body = ResumeTextIn.model_validate(await request.json())
        except ValidationError as exc:
            raise RequestValidationError(exc.errors(include_url=False)) from exc
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Request body is not valid JSON.") from exc
        return await run_in_threadpool(_resume_from_text, body.text, user, db, gw)
    raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send a multipart 'file' upload or a JSON body with 'text'.")


@router.get("/resumes", response_model=list[ResumeOut])
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(ResumeProfile).where(ResumeProfile.owner_id == user.id).order_by(ResumeProfile.created_at.desc())).all()


@router.get("/resumes/{resume_id}", response_model=ResumeOut)
def get_resume(resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _owned(ResumeProfile, resume_id, user, db, "Resume")


@router.put("/resumes/{resume_id}", response_model=ResumeOut)
def update_resume(resume_id: str, body: ResumeUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    resume = _owned(ResumeProfile, resume_id, user, db, "Resume")
    resume.parsed = normalize_resume_edit(body.parsed.model_dump())
    resume.user_confirmed = True
    db.commit()
    return resume


@router.delete("/resumes/{resume_id}", status_code=204)
def delete_resume(resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_owned(ResumeProfile, resume_id, user, db, "Resume"))  # preps cascade in the database
    db.commit()


# ---------- jobs ----------

def _apply_job(job: JobProfile, parsed: dict) -> None:
    job.parsed = parsed
    job.role_title = parsed["role_title"][:255]
    job.company = parsed["company"]
    job.seniority = parsed["seniority"]


def _job_out(job: JobProfile) -> JobOut:
    return JobOut(id=job.id, parsed=job.parsed, user_confirmed=job.user_confirmed, created_at=job.created_at, updated_at=job.updated_at)


@router.post("/jobs", response_model=JobOut, status_code=201)
def create_job(body: JobCreate, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    try:
        text = prepare_text(body.text, "job description").text
    except InputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    outcome = _ai_call(svc.parse_job, gw, text)
    if outcome.warnings:
        log.info("job parse dropped %d unverified item(s)", len(outcome.warnings))
    job = JobProfile(owner_id=user.id, raw_text=text, user_confirmed=False)
    _apply_job(job, outcome.parsed)
    db.add(job)
    db.commit()
    return _job_out(job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _job_out(_owned(JobProfile, job_id, user, db, "Job"))


@router.put("/jobs/{job_id}", response_model=JobOut)
def update_job(job_id: str, body: JobUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = _owned(JobProfile, job_id, user, db, "Job")
    _apply_job(job, normalize_job_edit(body.parsed.model_dump()))
    job.user_confirmed = True
    db.commit()
    return _job_out(job)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_owned(JobProfile, job_id, user, db, "Job"))
    db.commit()


# ---------- preps ----------

def _owned_prep(prep_id: str, user: User, db: Session) -> RolePrep:
    return _owned(RolePrep, prep_id, user, db, "Prep")


def _full_recompute(prep: RolePrep, user: User, db: Session, gw: Gateway) -> None:
    """Model judges evidence afresh (resume/JD may have changed), then code scores everything."""
    job, resume = _parents(prep, user, db)
    judgements = _ai_call(svc.match_skills, gw, job.parsed, resume.parsed)
    results = _score(prep, job, resume, judgements, user, db)
    svc.link_sources(results, job.parsed, _chunks(prep.document_ids, user, db))
    _save_matrix(prep, results, user, db)


@router.post("/preps", response_model=PrepOut, status_code=201)
def create_prep(body: PrepCreate, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    _owned(ResumeProfile, body.resume_id, user, db, "Resume")
    _owned(JobProfile, body.job_id, user, db, "Job")
    prep = RolePrep(
        owner_id=user.id, resume_id=body.resume_id, job_id=body.job_id,
        document_ids=_ready_document_ids(body.document_ids, user, db), interview_date=body.interview_date, plan=[],
    )
    db.add(prep)
    db.flush()
    _full_recompute(prep, user, db, gw)
    db.commit()
    analytics.record(db, user, "gap_report_ready", {"source": "prep"})
    dispatch("rebuild_graph", {"owner_id": user.id}, background, db=db)  # link the new skills to concepts
    return _prep_out(prep, user, db)


@router.get("/preps", response_model=list[PrepSummary])
def list_preps(user: User = Depends(current_user), db: Session = Depends(get_db)):
    preps = db.scalars(select(RolePrep).where(RolePrep.owner_id == user.id).order_by(RolePrep.updated_at.desc())).all()
    if not preps:
        return []
    ids = [p.id for p in preps]
    jobs = {j.id: j for j in db.scalars(select(JobProfile).where(JobProfile.id.in_({p.job_id for p in preps}), JobProfile.owner_id == user.id))}
    sessions = dict(db.execute(
        select(InterviewSession.prep_id, func.count()).where(InterviewSession.prep_id.in_(ids), InterviewSession.owner_id == user.id)
        .group_by(InterviewSession.prep_id)
    ).all())
    out = []
    for p in preps:
        job = jobs.get(p.job_id)
        critical = sum(1 for s in p.skills if s.gap_type != "strong" and ((s.user_override or {}).get("priority") or s.priority) == "critical")
        out.append(PrepSummary(
            id=p.id, role_title=job.role_title if job else "", company=job.company if job else None,
            interview_date=p.interview_date, critical_gaps=critical, sessions=sessions.get(p.id, 0), updated_at=p.updated_at,
        ))
    return out


@router.get("/preps/{prep_id}", response_model=PrepOut)
def get_prep(prep_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _prep_out(_owned_prep(prep_id, user, db), user, db)


@router.post("/preps/{prep_id}/recompute", response_model=PrepOut)
def recompute_prep(prep_id: str, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    prep = _owned_prep(prep_id, user, db)
    _full_recompute(prep, user, db, gw)
    db.commit()
    dispatch("rebuild_graph", {"owner_id": user.id}, background, db=db)
    return _prep_out(prep, user, db)


@router.get("/preps/{prep_id}/study-links", response_model=dict[str, list[StudyLinkOut]])
def prep_study_links(prep_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Where in the learner's own material each skill is taught: {skill_id: [concept, document, page]}."""
    from ..services.competency import study_links

    prep = _owned_prep(prep_id, user, db)
    by_name = study_links(db, user.id, [r.name for r in prep.skills])
    return {r.id: by_name[r.name] for r in prep.skills if r.name in by_name}


@router.patch("/preps/{prep_id}/skills/{skill_id}", response_model=SkillMatchOut)
def patch_skill(prep_id: str, skill_id: str, body: SkillPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prep = _owned_prep(prep_id, user, db)
    row = next((s for s in prep.skills if s.id == skill_id and s.owner_id == user.id), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill not found")
    override = dict(row.user_override or {})
    for field in body.model_fields_set & {"priority", "note"}:
        value = getattr(body, field)
        value = value.strip() if isinstance(value, str) else value
        if field == "priority" and value == row.priority:
            value = None  # "Use computed" re-sends the computed priority: clear the override, don't pin it
        if value:
            override[field] = value
        else:
            override.pop(field, None)
    row.user_override = override or None
    _rescore(prep, user, db)  # the override reorders the matrix and the plan
    db.commit()
    return _skill_out(row, _linked_sources(set(row.linked_chunk_ids), user, db))


@router.patch("/preps/{prep_id}", response_model=PrepOut)
def patch_prep(prep_id: str, body: PrepPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prep = _owned_prep(prep_id, user, db)
    fields = body.model_fields_set
    if "interview_date" in fields:
        prep.interview_date = body.interview_date
    relink = "document_ids" in fields and body.document_ids is not None
    if relink:
        prep.document_ids = _ready_document_ids(body.document_ids, user, db)
    if fields:
        _rescore(prep, user, db, relink=relink)
        db.commit()
    return _prep_out(prep, user, db)


@router.delete("/preps/{prep_id}", status_code=204)
def delete_prep(prep_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_owned_prep(prep_id, user, db))
    db.commit()


@router.get("/preps/{prep_id}/deep-dive", response_model=list[DeepDiveItem])
def deep_dive(prep_id: str, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    prep = _owned_prep(prep_id, user, db)
    job, resume = _parents(prep, user, db)
    return svc.deep_dive(gw, resume.parsed, job.role_title)


# ---------- mock interview sessions ----------

def _owned_session(sid: str, user: User, db: Session) -> InterviewSession:
    return _owned(InterviewSession, sid, user, db, "Session")


def _interview_context(prep: RolePrep, user: User, db: Session) -> isvc.InterviewContext:
    job, resume = _parents(prep, user, db)
    skills = [_row_result(r) for r in sorted(prep.skills, key=lambda r: r.rank)]
    return isvc.build_context(job.role_title, skills, job.parsed, resume.parsed)


def _state(session: InterviewSession) -> SessionState:
    return SessionState(session.focus, session.target_questions, [
        TurnState(t.kind, t.category, t.question, t.competency_id, t.competency_name, t.answer, t.evaluation)
        for t in session.turns
    ])


def _add_turn(session: InterviewSession, turn: TurnState, user: User) -> None:
    session.turns.append(InterviewTurn(
        owner_id=user.id, position=len(session.turns), kind=turn.kind, category=turn.category,
        competency_id=turn.competency_id, competency_name=turn.competency_name, question=turn.question,
    ))


def _complete(session: InterviewSession, state: SessionState, prep: RolePrep, user: User, db: Session) -> None:
    session.status = "completed"
    session.summary = isvc.summarize(state)
    session.ended_at = _now()
    db.flush()
    _rescore(prep, user, db)  # interview evidence can change gap types (e.g. communication gaps)


@router.post("/preps/{prep_id}/sessions", response_model=InterviewSessionOut, status_code=201)
def start_session(prep_id: str, body: SessionCreate | None = None, user: User = Depends(current_user),
                  db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    body = body or SessionCreate()
    prep = _owned_prep(prep_id, user, db)
    state = _ai_call(isvc.start_session, gw, _interview_context(prep, user, db), body.focus, body.target_questions)
    session = InterviewSession(
        owner_id=user.id, prep_id=prep.id, focus=body.focus, target_questions=body.target_questions,
        status="active", rubric_version=f"{RUBRIC_VERSION}/{gw.models['main']}"[:80],
    )
    db.add(session)
    for turn in state.turns:
        _add_turn(session, turn, user)
    db.commit()
    return session


@router.get("/preps/{prep_id}/sessions", response_model=list[SessionListItem])
def list_sessions(prep_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prep = _owned_prep(prep_id, user, db)
    sessions = db.scalars(
        select(InterviewSession).where(InterviewSession.prep_id == prep.id, InterviewSession.owner_id == user.id)
        .order_by(InterviewSession.started_at.desc())
    ).all()
    out = []
    for s in sessions:
        scores = [t.evaluation["score"] for t in s.turns if t.evaluation and t.evaluation.get("verdict") != "unassessed"]
        out.append(SessionListItem(
            id=s.id, focus=s.focus, status=s.status, questions=sum(1 for t in s.turns if t.kind == "question"),
            avg_score=round(sum(scores) / len(scores), 3) if scores else None, started_at=s.started_at,
        ))
    return out


@router.get("/sessions/{sid}", response_model=InterviewSessionOut)
def get_session(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _owned_session(sid, user, db)


@router.post("/sessions/{sid}/answer", response_model=InterviewSessionOut)
def answer(sid: str, body: AnswerIn, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    session = _owned_session(sid, user, db)
    if session.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This interview session has already ended.")
    if not session.turns or session.turns[-1].answer is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no open question to answer.")
    if not body.answer.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Write an answer first.")
    prep = _owned_prep(session.prep_id, user, db)
    state = _state(session)
    graded, asked = _ai_call(isvc.answer_turn, gw, _interview_context(prep, user, db), state, body.answer)

    row = session.turns[-1]
    row.answer, row.evaluation, row.answered_at = graded.answer, graded.evaluation, _now()
    if asked is not None:
        _add_turn(session, asked, user)
    else:
        _complete(session, state, prep, user, db)
    db.commit()
    return session


@router.post("/sessions/{sid}/end", response_model=InterviewSessionOut)
def end_session(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session = _owned_session(sid, user, db)
    if session.status != "completed":
        _complete(session, _state(session), _owned_prep(session.prep_id, user, db), user, db)
        db.commit()
    return session



# ---------- sharing (P3: read-only plan links) ----------

@router.post("/preps/{prep_id}/shares", response_model=ShareOut, status_code=201)
def create_share(prep_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..config import get_settings
    from ..services import sharing

    prep = _owned_prep(prep_id, user, db)
    share, token = sharing.create(db, user.id, prep)
    db.commit()
    analytics.record(db, user, "plan_shared")
    return ShareOut(id=share.id, url=f"{get_settings().web_url}/share/{token}", expires_at=share.expires_at,
                    views=0, created_at=share.created_at)


@router.get("/preps/{prep_id}/shares", response_model=list[ShareOut])
def list_shares(prep_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..services import sharing

    prep = _owned_prep(prep_id, user, db)
    return [ShareOut(id=s.id, expires_at=s.expires_at, views=s.views, created_at=s.created_at)
            for s in sharing.list_active(db, user.id, prep.id)]


@router.delete("/preps/{prep_id}/shares/{share_id}", status_code=204)
def revoke_share(prep_id: str, share_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..services import sharing

    _owned_prep(prep_id, user, db)
    if not sharing.revoke(db, user.id, share_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    db.commit()
