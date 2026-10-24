from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.gateway import PROMPT_VERSION, BudgetExceeded, Gateway, ModelError
from ..core.citations import SourceRef
from ..core.mastery import AttemptEvidence, estimate
from ..db import get_db
from ..deps import current_user, gateway_for
from ..models import Attempt, ChatMessage, Chunk, Document, Question, Quiz, User
from ..schemas import (
    AskIn,
    AskOut,
    AttemptIn,
    AttemptOut,
    FLAG_REASONS,
    FlaggedQuestionOut,
    FlagIn,
    MessageOut,
    ProgressOut,
    QuestionOut,
    QuizCreate,
    QuizOut,
    QuizSummary,
)
from ..services.knowledge_graph import upsert_concepts
from ..services.learning import ChunkData, ask_tutor, generate_quiz, grade_answer
from ..services import analytics
from ..jobs import dispatch
from ..services.graph import canonical_concept, concept_aliases, graph_hints

router = APIRouter(tags=["learning"])
log = logging.getLogger("mindmesh.learning")


# ---------- helpers ----------

def _ready_documents(ids: list[str], user: User, db: Session) -> dict[str, Document]:
    docs = db.scalars(select(Document).where(Document.id.in_(ids), Document.owner_id == user.id)).all()
    found = {d.id: d for d in docs}
    missing = set(ids) - set(found)
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more documents were not found.")
    # A long document being processed is usable once its first pages are saved (pages_done).
    not_ready = [d.filename for d in docs
                 if d.status not in ("ready", "needs_attention") and not (d.status == "processing" and d.pages_done)]
    if not_ready:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Still processing: {', '.join(not_ready)}")
    return found


def _dense_scores(db: Session, owner_id: str, chunk_ids: list[str], question: str) -> dict[str, float] | None:
    """Dense retrieval is an enhancement: if the embeddings provider fails, answer without it."""
    from ..services.embeddings_store import dense_scores

    try:
        return dense_scores(db, owner_id, chunk_ids, question)
    except Exception as exc:  # noqa: BLE001
        log.warning("dense retrieval skipped: %s", type(exc).__name__)
        return None


def _load_chunks(doc_ids: list[str], user: User, db: Session) -> list[ChunkData]:
    rows = db.scalars(
        select(Chunk).where(Chunk.document_id.in_(doc_ids), Chunk.owner_id == user.id).order_by(Chunk.document_id, Chunk.ordinal)
    ).all()
    return [ChunkData(c.id, c.text, c.page_start, c.page_end, c.section, c.document_id) for c in rows]


def _ai_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI service is temporarily unavailable. Your data is safe; please retry.") from exc


def _source_info(chunk_ids: list[str], user: User, db: Session) -> list[dict]:
    if not chunk_ids:
        return []
    rows = db.execute(
        select(Chunk.id, Chunk.document_id, Chunk.page_start, Chunk.page_end, Chunk.section, Document.title, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(chunk_ids), Chunk.owner_id == user.id)
    ).all()
    return [
        {"chunk_id": r[0], "document_id": r[1], "page_start": r[2], "page_end": r[3], "section": r[4], "document_title": r[5] or r[6]}
        for r in rows
    ]


# ---------- tutor ----------

@router.post("/tutor/ask", response_model=AskOut)
def ask(body: AskIn, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    docs = _ready_documents(body.document_ids, user, db)
    chunks = _load_chunks(list(docs), user, db)
    history_rows = db.scalars(
        select(ChatMessage).where(ChatMessage.owner_id == user.id).order_by(ChatMessage.created_at.desc()).limit(6)
    ).all()
    history = [(m.role, m.content) for m in reversed(history_rows) if set(m.document_ids) == set(body.document_ids)]

    hints = graph_hints(db, user.id, body.document_ids)  # P2: concept aliases and defining passages
    dense = _dense_scores(db, user.id, [c.id for c in chunks], body.question)  # P2: learned embeddings, if on
    result = _ai_call(ask_tutor, gw, chunks, body.question, body.level, history, body.allow_general, hints, dense)

    chunk_doc = {c.id: c.document_id for c in chunks}
    citations = [
        {**c, "document_id": chunk_doc[c["chunk_id"]], "document_title": docs[chunk_doc[c["chunk_id"]]].title or docs[chunk_doc[c["chunk_id"]]].filename}
        for c in result.citations
    ]
    db.add(ChatMessage(owner_id=user.id, document_ids=body.document_ids, role="user", content=body.question))
    db.add(ChatMessage(owner_id=user.id, document_ids=body.document_ids, role="assistant", content=result.answer, status=result.status, citations=citations))
    db.commit()
    analytics.record(db, user, "tutor_answer", {"status": result.status})
    return AskOut(answer=result.answer, status=result.status, citations=citations)


@router.get("/tutor/history", response_model=list[MessageOut])
def history(document_ids: list[str] = Query(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.owner_id == user.id).order_by(ChatMessage.created_at.asc())
    ).all()
    wanted = set(document_ids)
    return [m for m in rows if set(m.document_ids) == wanted][-100:]


# ---------- quizzes ----------

def _attempt_out(a: Attempt, q: Question) -> AttemptOut:
    return AttemptOut(
        id=a.id, verdict=a.verdict, score=a.score, feedback=a.feedback,
        missing=[c["criterion"] for c in a.criteria if c.get("status") != "met"],
        criteria=a.criteria, answer_key=q.answer_key, explanation=q.explanation,
        correct_index=q.correct_index, selected_index=a.selected_index,
        response_text=a.response_text, created_at=a.created_at,
    )


def _quiz_out(quiz: Quiz, user: User, db: Session) -> QuizOut:
    qids = [q.id for q in quiz.questions]
    latest: dict[str, Attempt] = {}
    if qids:
        for a in db.scalars(select(Attempt).where(Attempt.question_id.in_(qids), Attempt.owner_id == user.id).order_by(Attempt.created_at)):
            latest[a.question_id] = a
    all_chunk_ids = list({cid for q in quiz.questions for cid in q.source_chunk_ids})
    info = {s["chunk_id"]: s for s in _source_info(all_chunk_ids, user, db)}
    return QuizOut(
        id=quiz.id, title=quiz.title, focus=quiz.focus, document_ids=quiz.document_ids, created_at=quiz.created_at,
        questions=[
            QuestionOut(
                id=q.id, position=q.position, qtype=q.qtype, concept=q.concept, difficulty=q.difficulty,
                prompt=q.prompt, options=q.options, flagged=bool(q.flagged),
                sources=[info[c] for c in q.source_chunk_ids if c in info],
                last_attempt=_attempt_out(latest[q.id], q) if q.id in latest else None,
            )
            for q in quiz.questions
        ],
    )


def _owned_quiz(quiz_id: str, user: User, db: Session) -> Quiz:
    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == user.id))
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    return quiz


@router.post("/quizzes", response_model=QuizOut, status_code=201)
def create_quiz(body: QuizCreate, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    docs = _ready_documents(body.document_ids, user, db)
    chunks = _load_chunks(list(docs), user, db)
    if not chunks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "These documents have no readable text to build a quiz from.")
    generated = _ai_call(generate_quiz, gw, chunks, body.count, body.difficulty, body.focus)
    if not generated:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not generate valid questions. Try a different focus or retry.")

    names = ", ".join((d.title or d.filename) for d in docs.values())
    quiz = Quiz(owner_id=user.id, document_ids=body.document_ids, focus=body.focus,
                title=(f"{body.focus} — " if body.focus else "") + names[:200])
    db.add(quiz)
    db.flush()
    for i, g in enumerate(generated):
        s = g.spec
        db.add(Question(
            quiz_id=quiz.id, owner_id=user.id, position=i, qtype=s.type, concept=s.concept, difficulty=s.difficulty,
            prompt=s.prompt, options=s.options, correct_index=s.correct_index, answer_key=s.answer_key,
            rubric=[{"criterion": r.criterion, "points": r.points} for r in s.rubric],
            explanation=s.explanation, source_chunk_ids=g.source_chunk_ids,
            generator_version=f"{gw.models['fast']}@{PROMPT_VERSION}",
        ))
    upsert_concepts(db, user.id, [g.spec.concept for g in generated])
    db.commit()
    analytics.record(db, user, "quiz_created", {"count": len(generated)})
    dispatch("rebuild_graph", {"owner_id": user.id}, background, db=db)  # new concept names may merge
    db.refresh(quiz)
    return _quiz_out(quiz, user, db)


@router.get("/quizzes", response_model=list[QuizSummary])
def list_quizzes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    quizzes = db.scalars(select(Quiz).where(Quiz.owner_id == user.id).order_by(Quiz.created_at.desc())).all()
    out = []
    for quiz in quizzes:
        qids = [q.id for q in quiz.questions]
        latest: dict[str, float] = {}
        if qids:
            for a in db.scalars(select(Attempt).where(Attempt.question_id.in_(qids), Attempt.owner_id == user.id).order_by(Attempt.created_at)):
                latest[a.question_id] = a.score
        out.append(QuizSummary(
            id=quiz.id, title=quiz.title, created_at=quiz.created_at, question_count=len(qids),
            answered=len(latest), avg_score=round(sum(latest.values()) / len(latest), 3) if latest else None,
        ))
    return out


@router.get("/quizzes/{quiz_id}", response_model=QuizOut)
def get_quiz(quiz_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _quiz_out(_owned_quiz(quiz_id, user, db), user, db)


@router.delete("/quizzes/{quiz_id}", status_code=204)
def delete_quiz(quiz_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_owned_quiz(quiz_id, user, db))
    db.commit()


def _owned_question(qid: str, user: User, db: Session) -> Question:
    q = db.scalar(select(Question).where(Question.id == qid, Question.owner_id == user.id))
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    return q


@router.post("/questions/{qid}/attempts", response_model=AttemptOut, status_code=201)
def submit_attempt(qid: str, body: AttemptIn, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    q = _owned_question(qid, user, db)
    if q.qtype == "mcq":
        if body.selected_index is None or not 0 <= body.selected_index < len(q.options):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose one of the options.")
        sources: list[SourceRef] = []
    else:
        if not body.answer_text or not body.answer_text.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Write an answer first.")
        rows = db.scalars(select(Chunk).where(Chunk.id.in_(q.source_chunk_ids), Chunk.owner_id == user.id)).all()
        sources = [SourceRef(f"S{i}", c.id, c.text, c.page_start, c.page_end, c.section) for i, c in enumerate(rows, 1)]

    grade = _ai_call(
        grade_answer, gw, q.qtype, q.prompt, q.answer_key, q.rubric, q.options, q.correct_index,
        q.explanation, sources, body.answer_text, body.selected_index,
    )
    a = Attempt(
        owner_id=user.id, question_id=q.id, response_text=body.answer_text, selected_index=body.selected_index,
        confidence=body.confidence, verdict=grade.verdict, score=grade.score, feedback=grade.feedback,
        criteria=grade.criteria, evaluator_version="rules@1" if q.qtype == "mcq" else f"{gw.models['main']}@{PROMPT_VERSION}",
    )
    db.add(a)
    db.commit()
    analytics.record(db, user, "question_answered", {"qtype": q.qtype})
    return _attempt_out(a, q)


@router.post("/questions/{qid}/flag", status_code=204)
def flag_question(qid: str, body: FlagIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """FR-045: user reports an ambiguous or wrong question. Flagged items are excluded from mastery."""
    q = _owned_question(qid, user, db)
    reason = body.reason.strip()
    note = body.note.strip()
    if reason not in FLAG_REASONS:  # legacy free-text report
        reason, note = "other", (note or reason)
    q.flag_reason = reason
    q.flagged = note or reason  # non-null marks the question as reported
    q.flagged_at = datetime.now(timezone.utc)
    db.commit()


@router.delete("/questions/{qid}/flag", status_code=204)
def unflag_question(qid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Withdraw a report: the question counts towards mastery again."""
    q = _owned_question(qid, user, db)
    q.flagged, q.flag_reason, q.flagged_at = None, None, None
    db.commit()


@router.get("/questions/flagged", response_model=list[FlaggedQuestionOut])
def flagged_questions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The user's own reported questions, newest first (their triage list)."""
    rows = db.execute(
        select(Question, Quiz.title)
        .join(Quiz, Quiz.id == Question.quiz_id)
        .where(Question.owner_id == user.id, Question.flagged.is_not(None))
        .order_by(Question.flagged_at.desc(), Question.id)
    ).all()
    return [FlaggedQuestionOut(
        id=q.id, quiz_id=q.quiz_id, quiz_title=title, prompt=q.prompt, concept=q.concept,
        reason=q.flag_reason or "other", note="" if q.flagged == (q.flag_reason or "") else (q.flagged or ""),
        flagged_at=q.flagged_at,
    ) for q, title in rows]


# ---------- progress ----------

@router.get("/progress", response_model=ProgressOut)
def progress(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Attempt, Question)
        .join(Question, Question.id == Attempt.question_id)
        .where(Attempt.owner_id == user.id, Question.flagged.is_(None))
        .order_by(Attempt.created_at)
    ).all()
    by_concept: dict[str, list[AttemptEvidence]] = defaultdict(list)
    aliases = concept_aliases(db, user.id)  # merged concepts ("WIP", "Work in process") count as one
    for a, q in rows:
        if a.verdict == "unassessed":
            continue
        by_concept[canonical_concept(q.concept, aliases)].append(AttemptEvidence(a.score, q.qtype, q.difficulty, a.created_at))
    concepts = sorted((estimate(c, ev) for c, ev in by_concept.items()), key=lambda m: (m.level != "weak", m.estimate))

    doc_count = len(db.scalars(select(Document.id).where(Document.owner_id == user.id)).all())
    quiz_count = len(db.scalars(select(Quiz.id).where(Quiz.owner_id == user.id)).all())
    if doc_count == 0:
        nxt = {"type": "upload", "label": "Upload your first PDF", "reason": "Everything starts from your own material."}
    elif quiz_count == 0:
        nxt = {"type": "quiz", "label": "Take a first diagnostic quiz", "reason": "We need a few answers before we can see what you already know."}
    elif (due := [m for m in concepts if m.due_for_review]):
        names = ", ".join(m.concept for m in due[:3])
        nxt = {"type": "review", "label": f"Review: {names}", "focus": due[0].concept,
               "reason": due[0].explanation}
    elif (unv := [m for m in concepts if m.level == "unverified"]):
        nxt = {"type": "quiz", "label": f"Practise more on {unv[0].concept}", "focus": unv[0].concept,
               "reason": unv[0].explanation}
    else:
        nxt = {"type": "quiz", "label": "Try a harder applied quiz", "reason": "Your current concepts look solid. Stretch with application questions."}

    totals = {
        "documents": doc_count, "quizzes": quiz_count, "attempts": len(rows),
        "strong": sum(m.level == "strong" for m in concepts),
        "developing": sum(m.level == "developing" for m in concepts),
        "weak": sum(m.level == "weak" for m in concepts),
        "unverified": sum(m.level == "unverified" for m in concepts),
    }
    return ProgressOut(concepts=[m.__dict__ for m in concepts], totals=totals, next_action=nxt)
