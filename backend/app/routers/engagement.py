"""Today, timed sessions, weekly target, onboarding, debriefs. Owned by W2. Contract: docs/CONTRACTS.md §7.

Thin adapter over `app.services.engagement`. Every lookup filters by owner_id,
so other users' resources return 404. No model calls happen here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Quiz, User
from ..models_engagement import InterviewDebrief, StudySession
from ..models_interview import JobProfile, RolePrep
from ..schemas_engagement import (
    EventIn,
    ExperimentsOut,
    DebriefIn,
    DebriefOut,
    Prefs,
    PrefsPatch,
    SessionCreate,
    StepPatch,
    StudySessionOut,
    TodayPreview,
    WeekOut,
)
from ..services import engagement as svc
from ..services import analytics

router = APIRouter(tags=["engagement"])


# ---------- helpers ----------

def _session_out(s: StudySession) -> StudySessionOut:
    return StudySessionOut.model_validate({
        "id": s.id, "minutes": s.minutes, "steps": list(s.steps or []), "status": s.status,
        "wins": list(s.wins or []), "started_at": svc._aware(s.started_at),
        "completed_at": svc._aware(s.completed_at) if s.completed_at else None,
    })


def _owned_session(sid: str, user: User, db: Session) -> StudySession:
    s = db.scalar(select(StudySession).where(StudySession.id == sid, StudySession.owner_id == user.id))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return s


def _owned_prep(prep_id: str, user: User, db: Session) -> RolePrep:
    prep = db.scalar(select(RolePrep).where(RolePrep.id == prep_id, RolePrep.owner_id == user.id))
    if prep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prep not found")
    return prep


# ---------- prefs ----------

@router.get("/me/prefs", response_model=Prefs)
def get_prefs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return Prefs(**svc.prefs_dict(svc.get_prefs(user, db)))


@router.patch("/me/prefs", response_model=Prefs)
def patch_prefs(body: PrefsPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prefs = svc.get_prefs(user, db)
    svc.apply_prefs_patch(prefs, body.model_dump(exclude_unset=True))
    db.commit()
    return Prefs(**svc.prefs_dict(prefs))


# ---------- today / week ----------

@router.get("/today/preview", response_model=TodayPreview)
def today_preview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return TodayPreview.model_validate(svc.today_preview(user, db))


@router.get("/week", response_model=WeekOut)
def week(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return WeekOut.model_validate(svc.week(user, db))


# ---------- study sessions ----------

@router.post("/sessions/study", response_model=StudySessionOut, status_code=201)
def start_session(body: SessionCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = svc.start_session(user, db, body.minutes)
    if s is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "There's nothing to practise yet. Add a document or set up an interview prep first.")
    return _session_out(s)


@router.get("/sessions/study/{sid}", response_model=StudySessionOut)
def get_session(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _session_out(_owned_session(sid, user, db))


@router.patch("/sessions/study/{sid}/steps/{step_id}", response_model=StudySessionOut)
def update_step(sid: str, step_id: str, body: StepPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _owned_session(sid, user, db)
    if s.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This session is already finished.")
    if body.quiz_id is not None:
        if db.scalar(select(Quiz.id).where(Quiz.id == body.quiz_id, Quiz.owner_id == user.id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    if not svc.update_step(s, step_id, body.status, body.quiz_id, db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Step not found")
    db.refresh(s)
    return _session_out(s)


@router.post("/sessions/study/{sid}/complete", response_model=StudySessionOut)
def complete_session(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _owned_session(sid, user, db)
    if s.status == "abandoned":
        raise HTTPException(status.HTTP_409_CONFLICT, "This session was abandoned.")
    was_open = s.status != "completed"
    svc.complete_session(user, s, db)  # idempotent: a completed session is returned unchanged
    if was_open:
        analytics.record(db, user, "session_completed", {"minutes": int(s.minutes or 0)})
    return _session_out(s)


# ---------- interview debrief ----------

@router.post("/interview/preps/{prep_id}/debrief", response_model=DebriefOut, status_code=201)
def debrief(prep_id: str, body: DebriefIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prep = _owned_prep(prep_id, user, db)
    job = db.scalar(select(JobProfile).where(JobProfile.id == prep.job_id, JobProfile.owner_id == user.id))
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prep not found")
    if db.scalar(select(InterviewDebrief.id).where(InterviewDebrief.prep_id == prep.id, InterviewDebrief.owner_id == user.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "You've already told us how this interview went.")

    follow_up = None
    if body.next_step == "next_round":
        new = svc.copy_prep(prep, db)
        follow_up = {"type": "prep", "id": new.id}
    elif body.next_step == "learning_goal":
        topics = svc.remaining_gap_topics(prep, db)
        if not topics:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "This prep has no gaps left to learn. Pick another next step.")
        goal = svc.learning_goal_from_prep(prep, job, topics, db)
        follow_up = {"type": "goal", "id": goal.id}

    d = InterviewDebrief(owner_id=user.id, prep_id=prep.id, outcome=body.outcome, note=body.note.strip(),
                         next_step=body.next_step, interview_date=prep.interview_date)
    db.add(d)
    db.commit()
    return DebriefOut(id=d.id, prep_id=d.prep_id, outcome=d.outcome, note=d.note, next_step=d.next_step,
                      created_at=svc._aware(d.created_at), follow_up=follow_up)


# ---------- product analytics (content-free; services/analytics.py) ----------

@router.get("/me/experiments", response_model=ExperimentsOut)
def experiments(user: User = Depends(current_user)):
    """The user's stable variant for each running experiment."""
    return ExperimentsOut(onboarding=analytics.variant("onboarding", user.id))


@router.post("/events", status_code=204)
def client_event(body: EventIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The few events only the browser can see (an onboarding shown or chosen). Others are recorded server-side."""
    if body.name not in analytics.CLIENT_EVENTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown event.")
    props = dict(body.props)
    if body.name == "onboarding_shown":  # the server says which arm, so a client can't skew the experiment
        props = {"experiment": "onboarding", "variant": analytics.variant("onboarding", user.id)}
    analytics.record(db, user, body.name, props)



# ---------- skill taxonomy (P3; services/taxonomy.py) ----------

@router.get("/taxonomy")
def taxonomy_list(user: User = Depends(current_user)):
    """The shared, curated skill list (read-only reference data)."""
    from ..services.taxonomy import load

    data = load()
    return {"version": data["version"],
            "skills": [{k: v for k, v in s.items() if not k.startswith("_")} for s in data["skills"]]}


@router.get("/me/skill-profile")
def my_skill_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Your skills on the shared taxonomy: your concepts and job skills under each, mastery, roles asking for it."""
    from ..services.taxonomy import skill_profile

    return skill_profile(db, user.id)


@router.get("/me/journey")
def my_journey(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The notebook cover: trail stages (progress, never gates), where you left off, and your goals."""
    from ..services.journey import journey

    return journey(db, user.id)


@router.get("/me/graph")
def my_knowledge_map(limit: int = 150, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Your knowledge map: concepts, prerequisite links, sources (page + quote), mastery and skill per concept."""
    from ..services.graph_view import knowledge_map

    return knowledge_map(db, user.id, limit)



# ---------- push notifications (P3; app/push.py) ----------

class PushTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=255)
    platform: Literal["ios", "android"]


@router.post("/me/push-tokens", status_code=204)
def register_push_token(body: PushTokenIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Register this device for reminders (the app asks the OS for permission first). Idempotent."""
    from datetime import datetime, timezone

    from ..jobs import system_context
    from ..models_push import PushToken
    from ..push import valid_token

    if not valid_token(body.token):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That isn't a push token.")
    with system_context():  # a device that changed hands: the token moves to whoever signs in on it now
        other = db.scalar(select(PushToken).where(PushToken.token == body.token))
        if other is not None and other.owner_id != user.id:
            db.delete(other)
            db.flush()
        row = other if other is not None and other.owner_id == user.id else None
        now = datetime.now(timezone.utc)
        if row is None:
            db.add(PushToken(owner_id=user.id, token=body.token, platform=body.platform, last_seen_at=now))
        else:
            row.last_seen_at, row.disabled_at, row.platform = now, None, body.platform
        db.commit()


@router.delete("/me/push-tokens", status_code=204)
def remove_push_token(body: PushTokenIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Stop pushes to this device (sign-out, or notifications turned off in the app)."""
    from sqlalchemy import delete as sa_delete

    from ..models_push import PushToken

    db.execute(sa_delete(PushToken).where(PushToken.owner_id == user.id, PushToken.token == body.token))
    db.commit()
