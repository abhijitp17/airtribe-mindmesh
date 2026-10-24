"""The notebook cover (P4, DECISIONS #67): where the learner is on the trail, and where they left off.

Trail stages are progress, never gates: every stage links somewhere useful at any time.
  learn      at least one usable document in the library
  practise   at least PRACTISE_DONE assessed answers
  prove      at least PROVE_DONE concepts rated strong (knowledge tracing)
  interview  at least one finished mock interview
`resume` is the single most recent unfinished thing (an open session, mock interview or quiz, or the
last document worked in), for the cover's "Continue where you left off" ribbon.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Attempt, ChatMessage, Document, Question, Quiz
from ..models_engagement import StudySession
from ..models_goals import Goal
from ..models_interview import InterviewSession, JobProfile, RolePrep
from ..models_kg import KgNode

PRACTISE_DONE = 10
PROVE_DONE = 3
USABLE = ("ready", "needs_attention")


def _aware(t: datetime | None) -> datetime:
    if t is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def journey(db: Session, owner_id: str) -> dict:
    from .engagement import mastery

    docs = db.scalars(select(Document).where(Document.owner_id == owner_id, Document.status.in_(USABLE))
                      .order_by(Document.created_at.desc())).all()
    concepts = db.scalar(select(func.count()).select_from(KgNode).where(
        KgNode.owner_id == owner_id, KgNode.kind == "concept", KgNode.merged_into_id.is_(None))) or 0
    answers = db.scalar(select(func.count()).select_from(Attempt).where(
        Attempt.owner_id == owner_id, Attempt.verdict != "unassessed")) or 0
    levels = [m.level for m in mastery(owner_id, db).values()]
    strong, weak = levels.count("strong"), levels.count("weak")
    preps = db.execute(select(RolePrep, JobProfile.role_title, JobProfile.company)
                       .join(JobProfile, JobProfile.id == RolePrep.job_id)
                       .where(RolePrep.owner_id == owner_id).order_by(RolePrep.updated_at.desc())).all()
    mocks_done = db.scalar(select(func.count()).select_from(InterviewSession).where(
        InterviewSession.owner_id == owner_id, InterviewSession.status == "completed")) or 0
    first_prep = preps[0][0].id if preps else None

    stages = [
        {"key": "learn", "label": "Learn", "done": bool(docs),
         "detail": f"{_plural(len(docs), 'document')} · {_plural(concepts, 'concept')}" if docs else "Add what you're studying",
         "href": "/library"},
        {"key": "practise", "label": "Practise", "done": answers >= PRACTISE_DONE,
         "detail": _plural(answers, "answer") if answers else "Short quizzes from your notes", "href": "/#session"},
        {"key": "prove", "label": "Prove", "done": strong >= PROVE_DONE,
         "detail": f"{strong} strong · {weak} to work on" if levels else "Ideas you can show you know", "href": "/progress"},
        {"key": "interview", "label": "Interview", "done": mocks_done >= 1,
         "detail": _plural(mocks_done, "mock interview") if mocks_done else ("Practise out loud" if preps else "Add a role to prepare for"),
         "href": f"/interview/{first_prep}" if first_prep else "/interview/new"},
    ]
    current = next((s["key"] for s in stages if not s["done"]), None)
    notes = {
        "learn": "Add one thing you're studying. A chapter is enough to start your map.",
        "practise": f"Answer a few quick questions. {PRACTISE_DONE - answers} more and this stop is done.",
        "prove": f"Keep practising your weakest ideas until {PROVE_DONE} are strong ({strong} so far).",
        "interview": "Try a mock interview: questions from your role, answered out loud.",
        None: "Every stop is done. Keep your strongest ideas fresh with a short review.",
    }

    goals = [{"kind": "interview", "id": p.id, "title": role or "Interview prep", "subtitle": company or "",
              "date": p.interview_date.isoformat() if p.interview_date else None, "href": f"/interview/{p.id}"}
             for p, role, company in preps[:6]]
    goals += [{"kind": "goal", "id": g.id, "title": g.title, "subtitle": g.goal_type, "date": g.deadline.isoformat(),
               "href": f"/goals/{g.id}"}
              for g in db.scalars(select(Goal).where(Goal.owner_id == owner_id, Goal.status == "active")
                                  .order_by(Goal.deadline)).all()[:6]]

    return {"stages": stages, "current": current, "next_note": notes[current],
            "resume": _resume(db, owner_id, docs), "goals": goals}


def _resume(db: Session, owner_id: str, docs: list[Document]) -> dict | None:
    found: list[tuple[datetime, dict]] = []
    mock = db.scalar(select(InterviewSession).where(InterviewSession.owner_id == owner_id, InterviewSession.status == "active")
                     .order_by(InterviewSession.started_at.desc()))
    if mock:
        found.append((_aware(mock.started_at), {"kind": "interview", "title": "Finish your mock interview",
                                                "href": f"/interview/{mock.prep_id}/session/{mock.id}"}))
    study = db.scalar(select(StudySession).where(StudySession.owner_id == owner_id, StudySession.status == "active")
                      .order_by(StudySession.started_at.desc()))
    if study:
        found.append((_aware(study.started_at), {"kind": "session", "title": f"Finish your {study.minutes}-minute session",
                                                 "href": f"/session/{study.id}"}))
    last = db.execute(select(Attempt.created_at, Question.quiz_id).join(Question, Question.id == Attempt.question_id)
                      .where(Attempt.owner_id == owner_id).order_by(Attempt.created_at.desc()).limit(1)).first()
    if last:
        total = db.scalar(select(func.count()).select_from(Question).where(Question.quiz_id == last.quiz_id)) or 0
        done = db.scalar(select(func.count(func.distinct(Attempt.question_id))).join(Question, Question.id == Attempt.question_id)
                         .where(Attempt.owner_id == owner_id, Question.quiz_id == last.quiz_id)) or 0
        quiz = db.get(Quiz, last.quiz_id)
        if quiz is not None and done < total:
            found.append((_aware(last.created_at), {"kind": "quiz", "title": f"Finish your quiz ({done} of {total} answered)",
                                                    "href": f"/quiz/{quiz.id}"}))
    by_id = {d.id: d for d in docs}
    for msg in db.scalars(select(ChatMessage).where(ChatMessage.owner_id == owner_id, ChatMessage.role == "user")
                          .order_by(ChatMessage.created_at.desc()).limit(5)):
        doc = next((by_id[i] for i in (msg.document_ids or []) if i in by_id), None)
        if doc:
            found.append((_aware(msg.created_at), {"kind": "document", "title": f"Back to {doc.title or doc.filename}",
                                                   "href": f"/documents/{doc.id}"}))
            break
    if docs:
        found.append((_aware(docs[0].created_at), {"kind": "document", "title": f"Open {docs[0].title or docs[0].filename}",
                                                   "href": f"/documents/{docs[0].id}"}))
    return max(found, key=lambda f: f[0])[1] if found else None
