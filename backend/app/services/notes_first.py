"""Notes-first answers (P3): save tokens by answering from the knowledge base when that's reliable.

Order of attempts, cheapest first (only the last one costs tokens, and only on request):
  1. graph      questions about the learner's own learning (mastery, prerequisites, which notes
                cover a topic) are answered from the database.
  2. reused     a repeat of a question the AI already answered with verified citations, when every
                cited passage still exists unchanged.
  3. notes      the no-model coverage check is confident: the best-matching sentences, quoted
                verbatim with their pages.
  -  needs_ai   coverage is uncertain, or the question needs reasoning (compare, apply, why):
                the passages are shown free, with an estimate of what an AI answer would cost.
  -  not_found  nothing in the notes: a general AI answer is offered, clearly labelled.
  4. ai         only when the learner asks (`use_ai`): the normal cited tutor (or a general answer).
Every outcome is recorded as a `notes_answer` event (mode only) for the savings meter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.notes_first import classify, extract, question_key, same_question
from ..models import Chunk, ChatMessage, Document, UsageEvent, User
from ..models_analytics import ProductEvent
from . import analytics
from .learning import ChunkData, TutorResult, ask_tutor, lexical_coverage, retrieve

DEFAULT_AI_TOKENS = 3500  # until the learner has tutor usage of their own
REUSE_LOOKBACK = 300  # recent questions checked for a repeat
LOCAL_MODES = ("graph", "reused", "notes")


@dataclass
class NotesAnswer:
    mode: str  # graph | reused | notes | needs_ai | not_found | ai | general
    answer: str = ""
    citations: list[dict] = field(default_factory=list)
    passages: list[dict] = field(default_factory=list)  # free context when the AI is suggested
    reason: str = ""
    ai_tokens_estimate: int = 0
    status: str | None = None  # the tutor's status when mode is ai


def ai_tokens_estimate(db: Session, owner_id: str) -> int:
    avg = db.scalar(select(func.avg(UsageEvent.input_tokens + UsageEvent.output_tokens)).where(
        UsageEvent.owner_id == owner_id, UsageEvent.task.in_(("tutor", "answerable"))))
    return int(round(avg)) if avg else DEFAULT_AI_TOKENS


# ---------------------------------------------------------------- 1. graph questions

def _graph_answer(db: Session, user: User, kind: str, topic: str) -> NotesAnswer | None:
    from ..core.mastery import estimate
    from .concepts import documents_covering
    from .engagement import _evidence
    from .graph import canonical_concept, concept_aliases
    from .knowledge_graph import canonical_key, prerequisite_chain

    aliases = concept_aliases(db, user.id)
    name = canonical_concept(topic, aliases)
    known = canonical_key(topic) in aliases
    if kind == "mastery":
        ev = _evidence(user.id, db).by_concept
        attempts = next((a for c, a in ev.items() if canonical_key(c) == canonical_key(name)), None)
        if not attempts:
            if not known:
                return None
            return NotesAnswer("graph", f"You haven't answered any questions on {name} yet, so there's no rating. "
                                        f"A short quiz will show where you stand.", reason="mastery")
        m = estimate(name, attempts)
        level = {"strong": "strong", "developing": "developing", "weak": "still shaky", "unverified": "not rated yet"}[m.level]
        return NotesAnswer("graph", f"{name}: {level}. {m.explanation}", reason="mastery")
    if kind == "prerequisites":
        chain = prerequisite_chain(db, user.id, name, max_depth=3)
        if not chain:
            return None if not known else NotesAnswer(
                "graph", f"Your material doesn't say what {name} builds on yet.", reason="prerequisites")
        names = [n for n, _ in chain]
        return NotesAnswer("graph", f"{name} builds on: {', '.join(names)}. Start with {names[-1] if len(names) > 1 else names[0]}.",
                           reason="prerequisites")
    if kind == "documents":
        ids = documents_covering(db, user.id, name)
        if not ids:
            return None
        titles = [d.title or d.filename for d in db.scalars(select(Document).where(Document.owner_id == user.id,
                                                                                   Document.id.in_(ids)))]
        return NotesAnswer("graph", f"{name} is covered in: {'; '.join(titles)}.", reason="documents")
    return None


# ---------------------------------------------------------------- 2. reuse

def _reuse(db: Session, user: User, question: str, chunks: list[ChunkData]) -> NotesAnswer | None:
    key = question_key(question)
    live = {c.id: c for c in chunks}
    rows = db.scalars(select(ChatMessage).where(ChatMessage.owner_id == user.id)
                      .order_by(ChatMessage.created_at.desc()).limit(REUSE_LOOKBACK * 2)).all()
    rows = list(reversed(rows))  # oldest first, so an answer follows its question
    for i, msg in enumerate(rows[:-1]):
        nxt = rows[i + 1]
        if (msg.role != "user" or nxt.role != "assistant" or nxt.status != "verified"
                or not same_question(key, question_key(msg.content))):
            continue
        cites = nxt.citations or []
        # Reuse only if every cited passage is still in the searched documents, with the quote still in it.
        if cites and all(c.get("chunk_id") in live and " ".join(str(c.get("quote", "")).split())
                         in " ".join(live[c["chunk_id"]].text.split()) for c in cites):
            return NotesAnswer("reused", nxt.content, cites, reason="You asked this before; this is the verified answer.")
    return None


# ---------------------------------------------------------------- the flow

def _passages(sources) -> list[dict]:
    return [{"chunk_id": s.chunk_id, "text": s.text[:600], "page_start": s.page_start, "page_end": s.page_end,
             "section": s.section} for s in sources[:3]]


def answer(db: Session, user: User, question: str, chunks: list[ChunkData], *, use_ai: str | None = None,
           gw=None, hints=None, dense=None) -> NotesAnswer:
    """`use_ai`: None (never call a model), "explain" (cited tutor) or "general" (labelled general answer)."""
    estimate_tokens = ai_tokens_estimate(db, user.id)
    if use_ai in ("explain", "general"):
        result: TutorResult = ask_tutor(gw, chunks, question, allow_general=use_ai == "general", hints=hints, dense=dense)
        mode = "general" if result.status == "general" else "ai"
        return NotesAnswer(mode, result.answer, result.citations, status=result.status)

    result = _local_or_offer(db, user, question, chunks, estimate_tokens, hints, dense)
    by_id = {c.id: c.document_id for c in chunks}
    for c in result.citations + result.passages:  # link every quote and passage to its document
        c.setdefault("document_id", by_id.get(c.get("chunk_id"), ""))
    return result


def _local_or_offer(db, user, question, chunks, estimate_tokens, hints, dense) -> NotesAnswer:
    route = classify(question)
    if route.kind in ("mastery", "prerequisites", "documents"):
        got = _graph_answer(db, user, route.kind, route.topic)
        if got is not None:
            return got
    reused = _reuse(db, user, question, chunks)
    if reused is not None:
        return reused
    sources = retrieve(chunks, question, hints=hints, dense=dense)
    coverage = lexical_coverage(chunks, question, sources)
    if coverage == "not_found":
        return NotesAnswer("not_found", reason="Your notes don't cover this.", ai_tokens_estimate=estimate_tokens)
    if route.kind == "synthesis":
        return NotesAnswer("needs_ai", passages=_passages(sources), ai_tokens_estimate=estimate_tokens,
                           reason="This asks for reasoning across your notes, which needs the AI.")
    if coverage == "confident":
        ex = extract(question, sources)
        if ex is not None:
            return NotesAnswer("notes", ex.answer, ex.citations, reason="Quoted from your notes.")
    return NotesAnswer("needs_ai", passages=_passages(sources), ai_tokens_estimate=estimate_tokens,
                       reason="Your notes may cover this, but not clearly enough to answer without the AI.")


def record(db: Session, user: User, question: str, document_ids: list[str], result: NotesAnswer) -> None:
    """Keep local answers in the chat history (status "notes"), and count the outcome for the meter."""
    if result.mode in LOCAL_MODES and result.answer:
        db.add(ChatMessage(owner_id=user.id, document_ids=document_ids, role="user", content=question))
        db.add(ChatMessage(owner_id=user.id, document_ids=document_ids, role="assistant", content=result.answer,
                           status="notes", citations=result.citations))
        db.commit()
    analytics.record(db, user, "notes_answer", {"mode": result.mode})


def stats(db: Session, user: User, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.scalars(select(ProductEvent.props).where(ProductEvent.owner_id == user.id,
                                                       ProductEvent.name == "notes_answer",
                                                       ProductEvent.created_at >= since)).all()
    counts: dict[str, int] = {}
    for p in rows:
        m = str((p or {}).get("mode", ""))
        counts[m] = counts.get(m, 0) + 1
    local = sum(counts.get(m, 0) for m in LOCAL_MODES)
    ai = counts.get("ai", 0) + counts.get("general", 0)
    per = ai_tokens_estimate(db, user.id)
    return {"days": days, "from_notes": local, "with_ai": ai, "by_mode": counts,
            "tokens_saved_estimate": local * per, "tokens_per_ai_answer": per}


def ready_chunks(db: Session, owner_id: str, document_ids: list[str] | None) -> tuple[list[str], list[ChunkData]]:
    """The documents to search (all usable ones when none are given) and their chunks."""
    q = select(Document.id).where(Document.owner_id == owner_id, Document.status.in_(("ready", "needs_attention")))
    if document_ids:
        q = q.where(Document.id.in_(document_ids))
    ids = list(db.scalars(q))
    rows = db.scalars(select(Chunk).where(Chunk.document_id.in_(ids), Chunk.owner_id == owner_id)
                      .order_by(Chunk.document_id, Chunk.ordinal)).all() if ids else []
    return ids, [ChunkData(c.id, c.text, c.page_start, c.page_end, c.section, c.document_id) for c in rows]
