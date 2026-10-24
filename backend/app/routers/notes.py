"""Notes-first answers (services/notes_first.py): answer from the knowledge base, use the AI only on request."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..ai.gateway import BudgetExceeded, Gateway, ModelError
from ..db import get_db
from ..deps import current_user, gateway_for
from ..models import User
from ..services import notes_first as svc

router = APIRouter(prefix="/notes", tags=["notes"])


class NotesAskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    document_ids: list[str] | None = Field(default=None, max_length=50)  # default: all usable documents
    use_ai: Literal["explain", "general"] | None = None  # None: never call a model


class NotesAskOut(BaseModel):
    mode: str
    answer: str
    citations: list[dict]
    passages: list[dict]
    reason: str
    ai_tokens_estimate: int
    status: str | None = None


@router.post("/ask", response_model=NotesAskOut)
def ask(body: NotesAskIn, user: User = Depends(current_user), db: Session = Depends(get_db),
        gw: Gateway = Depends(gateway_for)):
    from ..services.graph import graph_hints

    doc_ids, chunks = svc.ready_chunks(db, user.id, body.document_ids)
    if body.document_ids and len(doc_ids) != len(set(body.document_ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more documents were not found or aren't ready.")
    hints = graph_hints(db, user.id, doc_ids) if chunks else None
    dense = None
    if body.use_ai and chunks:  # dense query embedding costs a (tiny) provider call: only on the AI path
        from .learning import _dense_scores
        dense = _dense_scores(db, user.id, [c.id for c in chunks], body.question)
    try:
        result = svc.answer(db, user, body.question, chunks, use_ai=body.use_ai, gw=gw, hints=hints, dense=dense)
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI service is temporarily unavailable. Please retry.") from exc
    svc.record(db, user, body.question, doc_ids, result)
    return NotesAskOut(**result.__dict__)


@router.get("/stats")
def notes_stats(days: int = 30, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The savings meter: answers from notes vs the AI, and tokens saved (estimate) over `days`."""
    return svc.stats(db, user, max(1, min(days, 365)))
