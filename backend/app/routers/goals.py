"""Goals & plans API (CONTRACTS §4, PRD FR-020..023).

The model proposes topics; app.core.planner schedules them. Every query is
scoped to the caller's owner_id and other users' rows return 404.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.gateway import BudgetExceeded, Gateway, ModelError
from ..clock import user_today
from ..core.mastery import AttemptEvidence, estimate
from ..core.planner import PlanEntry, TopicSpec, adapt, compute_stats
from ..db import get_db
from ..deps import current_user, gateway_for
from ..models import Attempt, Chunk, Document, Question, User
from ..models_goals import Goal, PlanItem, PlanProposal
from ..models_interview import RolePrep, SkillMatch
from ..schemas_goals import (
    GoalCreate,
    GoalOut,
    GoalPatch,
    GoalSummary,
    PlanItemCreate,
    PlanItemOut,
    PlanItemPatch,
    PlanProposalOut,
    RegenerateIn,
    TodayItem,
    TodayOut,
)
from ..services.goals import (
    build_plan,
    dropped_reason,
    goal_warning,
    is_dropped,
    propose_topics,
    topics_from_items,
    topics_from_skills,
)
from ..services.knowledge_graph import record_prerequisites, with_graph_prerequisites
from ..services.learning import ChunkData
from ..services.graph import canonical_concept, concept_aliases

router = APIRouter(tags=["goals"])

SCHEDULE_FIELDS = {"deadline", "minutes_per_day", "study_days"}
TOPIC_FIELDS = {"document_ids", "prep_id", "goal_type", "current_level"}


# ---------- helpers ----------

def _today() -> date:
    return user_today()  # the user's calendar day (X-Timezone), not the server's


def _ai_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI service is temporarily unavailable. Your data is safe; please retry.") from exc


def _owned_goal(goal_id: str, user: User, db: Session) -> Goal:
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.owner_id == user.id))
    if goal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found")
    return goal


def _owned_item(item_id: str, user: User, db: Session) -> PlanItem:
    item = db.scalar(select(PlanItem).where(PlanItem.id == item_id, PlanItem.owner_id == user.id))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    return item


def _check_documents(ids: list[str], user: User, db: Session) -> None:
    if not ids:
        return
    docs = db.scalars(select(Document).where(Document.id.in_(ids), Document.owner_id == user.id)).all()
    if set(ids) - {d.id for d in docs}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more documents were not found.")
    not_ready = [d.filename for d in docs if d.status not in ("ready", "needs_attention")]
    if not_ready:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Still processing: {', '.join(not_ready)}")


def _check_prep(prep_id: str | None, user: User, db: Session) -> None:
    if prep_id and db.scalar(select(RolePrep.id).where(RolePrep.id == prep_id, RolePrep.owner_id == user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Interview prep not found")


def _load_chunks(doc_ids: list[str], user: User, db: Session) -> list[ChunkData]:
    if not doc_ids:
        return []
    rows = db.scalars(
        select(Chunk).where(Chunk.document_id.in_(doc_ids), Chunk.owner_id == user.id).order_by(Chunk.document_id, Chunk.ordinal)
    ).all()
    order = {d: i for i, d in enumerate(doc_ids)}
    rows = sorted(rows, key=lambda c: (order.get(c.document_id, 0), c.ordinal))
    return [ChunkData(c.id, c.text, c.page_start, c.page_end, c.section, c.document_id) for c in rows]


def _source_map(chunk_ids: set[str], user: User, db: Session) -> dict[str, dict]:
    if not chunk_ids:
        return {}
    rows = db.execute(
        select(Chunk.id, Chunk.document_id, Chunk.page_start, Chunk.page_end, Chunk.section)
        .where(Chunk.id.in_(list(chunk_ids)), Chunk.owner_id == user.id)
    ).all()
    return {r[0]: {"chunk_id": r[0], "document_id": r[1], "page_start": r[2], "page_end": r[3], "section": r[4]} for r in rows}


def _item_dict(i: PlanItem, sources: dict[str, dict]) -> dict:
    return {
        "id": i.id, "position": i.position, "scheduled_date": i.scheduled_date, "topic": i.topic, "concept": i.concept,
        "activity_type": i.activity_type, "estimated_minutes": i.estimated_minutes, "objective": i.objective or "",
        "sources": [sources[c] for c in (i.source_chunk_ids or []) if c in sources],
        "status": i.status, "user_edited": bool(i.user_edited), "reason": i.reason or "",
    }


def _item_out(i: PlanItem, user: User, db: Session) -> PlanItemOut:
    return PlanItemOut(**_item_dict(i, _source_map(set(i.source_chunk_ids or []), user, db)))


def _proposal_out(p: PlanProposal) -> PlanProposalOut:
    return PlanProposalOut(id=p.id, reason=p.reason, changes=p.changes or [], status=p.status, created_at=p.created_at)


def _pending_proposal(goal: Goal, db: Session) -> PlanProposal | None:
    return db.scalar(
        select(PlanProposal)
        .where(PlanProposal.goal_id == goal.id, PlanProposal.owner_id == goal.owner_id, PlanProposal.status == "pending")
        .order_by(PlanProposal.created_at.desc())
    )


def _stats(goal: Goal, items: list[PlanItem], today: date) -> dict:
    return compute_stats([i for i in items if not is_dropped(i)], today, goal.deadline, goal.minutes_per_day, goal.study_days)


def _goal_out(goal: Goal, user: User, db: Session) -> GoalOut:
    today = _today()
    items = sorted(goal.items, key=lambda i: i.position)
    sources = _source_map({c for i in items for c in (i.source_chunk_ids or [])}, user, db)
    pending = _pending_proposal(goal, db)
    return GoalOut(
        id=goal.id, goal_type=goal.goal_type, title=goal.title, target_outcome=goal.target_outcome or "",
        deadline=goal.deadline, minutes_per_day=goal.minutes_per_day, study_days=list(goal.study_days or []),
        current_level=goal.current_level, document_ids=list(goal.document_ids or []), prep_id=goal.prep_id,
        status=goal.status, items=[PlanItemOut(**_item_dict(i, sources)) for i in items],
        pending_proposal=_proposal_out(pending) if pending else None,
        stats=_stats(goal, items, today),
        feasibility_warning=goal_warning(items, today, goal.deadline, goal.minutes_per_day, goal.study_days),
        created_at=goal.created_at,
    )


def _supersede_proposals(goal: Goal, db: Session) -> None:
    for p in db.scalars(select(PlanProposal).where(PlanProposal.goal_id == goal.id, PlanProposal.status == "pending")):
        p.status = "rejected"  # its item ids may no longer exist after a replan


def _renumber(goal_id: str, db: Session, first: PlanItem | None = None) -> None:
    db.flush()
    rows = db.scalars(select(PlanItem).where(PlanItem.goal_id == goal_id)).all()
    rows = sorted(rows, key=lambda i: (i.scheduled_date, 0 if i is first else 1, i.position))
    for pos, i in enumerate(rows):
        i.position = pos


def _skill_dicts(prep_id: str, user: User, db: Session) -> list[dict]:
    rows = db.scalars(
        select(SkillMatch).where(SkillMatch.prep_id == prep_id, SkillMatch.owner_id == user.id).order_by(SkillMatch.rank)
    ).all()
    return [
        {"name": s.name, "priority": s.priority, "gap_type": s.gap_type, "user_override": s.user_override,
         "linked_chunk_ids": list(s.linked_chunk_ids or []), "recommended_action": s.recommended_action}
        for s in rows
    ]


def _propose(goal: Goal, user: User, db: Session, gw: Gateway) -> list[TopicSpec]:
    """Interview goals with a prep: topics from skill gaps (no model). Otherwise the model proposes."""
    if goal.goal_type == "interview" and goal.prep_id:
        topics = topics_from_skills(_skill_dicts(goal.prep_id, user, db))
        if topics or not goal.document_ids:
            return topics
    chunks = _load_chunks(list(goal.document_ids or []), user, db)
    if not chunks:
        return []
    return _ai_call(
        propose_topics, gw, chunks, goal.goal_type, goal.title, goal.target_outcome or "",
        goal.current_level, goal.deadline, goal.minutes_per_day,
    )


def _replan(goal: Goal, user: User, db: Session, topics: list[TopicSpec] | None, keep_edited: bool = True) -> None:
    """Rebuild future, unedited sessions. `topics=None` reuses the current plan's topics (no model call).

    Kept in place: done/skipped history, anything in the past (missed sessions are only moved
    through /adapt), and user-edited items when keep_edited.
    """
    today = _today()
    items = list(goal.items)
    keep: list[PlanItem] = []
    remove: list[PlanItem] = []
    for i in items:
        if is_dropped(i):
            remove.append(i)
        elif i.status != "pending" or i.scheduled_date < today or (keep_edited and i.user_edited):
            keep.append(i)
        else:
            remove.append(i)
    scale = topics is not None
    if topics:
        # Keep the planner's "builds on" ordering as knowledge-graph edges (it used to be discarded),
        # and order foundations first where the learner's material says so (grounded edges).
        record_prerequisites(db, user.id, topics, {"goal_id": goal.id})
        topics = with_graph_prerequisites(db, user.id, topics)
    specs = topics if topics is not None else topics_from_items(items)
    fixed = [
        PlanEntry(i.scheduled_date, i.topic, i.activity_type, i.estimated_minutes, concept=i.concept,
                  objective=i.objective or "", source_chunk_ids=list(i.source_chunk_ids or []), reason=i.reason or "",
                  status=i.status, id=i.id, position=i.position, user_edited=bool(i.user_edited))
        for i in keep
    ]
    for i in remove:
        goal.items.remove(i)  # delete-orphan cascade deletes the row
    db.flush()

    entries, _warning, dropped = build_plan(
        today=today, goal_type=goal.goal_type, deadline=goal.deadline, minutes_per_day=goal.minutes_per_day,
        study_days=list(goal.study_days or []), level=goal.current_level, topics=specs, fixed=fixed,
        interview=goal.goal_type == "interview", scale=scale,
    )
    rows = {i.id: i for i in keep}
    for e in entries:
        if e.fixed and e.id in rows:
            rows[e.id].position = e.position
        elif not e.fixed:
            goal.items.append(PlanItem(
                goal_id=goal.id, owner_id=user.id, position=e.position, scheduled_date=e.scheduled_date,
                topic=e.topic[:255], concept=(e.concept or None) and e.concept[:120], activity_type=e.activity_type,
                estimated_minutes=e.estimated_minutes, objective=e.objective, source_chunk_ids=e.source_chunk_ids,
                status="pending", user_edited=False, reason=e.reason,
            ))
    base = len(entries)
    for k, t in enumerate(dropped):
        goal.items.append(PlanItem(
            goal_id=goal.id, owner_id=user.id, position=base + k, scheduled_date=goal.deadline,
            topic=t.topic[:255], concept=(t.concept or None) and t.concept[:120], activity_type=t.activity,
            estimated_minutes=t.est_minutes, objective=t.objective, source_chunk_ids=list(t.source_chunk_ids),
            status="skipped", user_edited=False, reason=dropped_reason(goal.minutes_per_day, goal.deadline),
        ))
    _supersede_proposals(goal, db)


def _commit_out(goal: Goal, user: User, db: Session) -> GoalOut:
    db.commit()
    db.refresh(goal)
    return _goal_out(goal, user, db)


def _mastery_levels(user: User, db: Session) -> dict[str, str]:
    rows = db.execute(
        select(Attempt, Question)
        .join(Question, Question.id == Attempt.question_id)
        .where(Attempt.owner_id == user.id, Question.flagged.is_(None))
        .order_by(Attempt.created_at)
    ).all()
    by_concept: dict[str, list[AttemptEvidence]] = defaultdict(list)
    aliases = concept_aliases(db, user.id)
    for a, q in rows:
        if a.verdict != "unassessed":
            by_concept[canonical_concept(q.concept, aliases)].append(AttemptEvidence(a.score, q.qtype, q.difficulty, a.created_at))
    return {c: estimate(c, ev).level for c, ev in by_concept.items()}


def _check_date(d: date, goal: Goal) -> None:
    if d > goal.deadline:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"That date is after your deadline ({goal.deadline.isoformat()}).")


# ---------- goals ----------

@router.post("/goals", response_model=GoalOut, status_code=201)
def create_goal(body: GoalCreate, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    if body.deadline < _today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The deadline is in the past.")
    _check_documents(body.document_ids, user, db)
    _check_prep(body.prep_id, user, db)
    if not body.document_ids and not (body.goal_type == "interview" and body.prep_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose at least one document to plan from.")
    goal = Goal(
        owner_id=user.id, goal_type=body.goal_type, title=body.title.strip(), target_outcome=body.target_outcome.strip(),
        deadline=body.deadline, minutes_per_day=body.minutes_per_day, study_days=body.study_days,
        current_level=body.current_level, document_ids=body.document_ids, prep_id=body.prep_id,
    )
    topics = _propose(goal, user, db, gw)  # before add: an AI failure leaves nothing behind
    if not topics and not (goal.goal_type == "interview" and goal.prep_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "These documents have no readable text to plan from.")
    db.add(goal)
    db.flush()
    _replan(goal, user, db, topics)
    return _commit_out(goal, user, db)


@router.get("/goals", response_model=list[GoalSummary])
def list_goals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = _today()
    goals = db.scalars(select(Goal).where(Goal.owner_id == user.id).order_by(Goal.created_at.desc())).all()
    out = []
    for g in goals:
        items = list(g.items)
        st = _stats(g, items, today)
        out.append(GoalSummary(
            id=g.id, title=g.title, goal_type=g.goal_type, deadline=g.deadline, status=g.status,
            items_done=st["items_done"], items_total=st["items_total"], on_track=st["on_track"],
            today_items=sum(1 for i in items if i.scheduled_date == today and i.status == "pending"),
        ))
    return out


@router.get("/goals/{goal_id}", response_model=GoalOut)
def get_goal(goal_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _goal_out(_owned_goal(goal_id, user, db), user, db)


@router.patch("/goals/{goal_id}", response_model=GoalOut)
def patch_goal(goal_id: str, body: GoalPatch, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    goal = _owned_goal(goal_id, user, db)
    data = body.model_dump(exclude_unset=True)
    for k in ("goal_type", "title", "target_outcome", "deadline", "minutes_per_day", "study_days", "current_level", "document_ids", "status"):
        if k in data and data[k] is None:
            del data[k]  # null means "unchanged" for required fields
    if "deadline" in data and data["deadline"] < _today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The deadline is in the past.")
    if "document_ids" in data:
        _check_documents(data["document_ids"], user, db)
    if data.get("prep_id"):
        _check_prep(data["prep_id"], user, db)

    changed = {k for k, v in data.items() if getattr(goal, k) != v}
    for k in changed:
        v = data[k]
        setattr(goal, k, v.strip() if isinstance(v, str) and k in ("title", "target_outcome") else v)

    if changed & TOPIC_FIELDS:
        if not goal.document_ids and not (goal.goal_type == "interview" and goal.prep_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose at least one document to plan from.")
        _replan(goal, user, db, _propose(goal, user, db, gw))
    elif changed & SCHEDULE_FIELDS:
        _replan(goal, user, db, None)
    return _commit_out(goal, user, db)


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_owned_goal(goal_id, user, db))
    db.commit()
    return Response(status_code=204)


@router.post("/goals/{goal_id}/regenerate", response_model=GoalOut)
def regenerate(goal_id: str, body: RegenerateIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db), gw: Gateway = Depends(gateway_for)):
    goal = _owned_goal(goal_id, user, db)
    keep = True if body is None else body.keep_edited
    topics = _propose(goal, user, db, gw)
    _replan(goal, user, db, topics, keep_edited=keep)
    return _commit_out(goal, user, db)


# ---------- plan items ----------

@router.patch("/plan-items/{item_id}", response_model=PlanItemOut)
def patch_item(item_id: str, body: PlanItemPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = _owned_item(item_id, user, db)
    goal = _owned_goal(item.goal_id, user, db)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not data:
        return _item_out(item, user, db)
    was_dropped = is_dropped(item)
    if "scheduled_date" in data:
        _check_date(data["scheduled_date"], goal)
    if "topic" in data:
        data["topic"] = data["topic"].strip()
        if not data["topic"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Topic can't be empty.")

    for k in ("scheduled_date", "estimated_minutes", "topic"):
        if k in data:
            setattr(item, k, data[k])
    if "status" in data:
        item.status = data["status"]
        item.completed_at = datetime.now(timezone.utc) if item.status == "done" else None
    if set(data) - {"status"}:
        item.user_edited = True
    if was_dropped and item.status != "skipped":
        # The user chose to add a left-out topic back. It no longer counts as "left out";
        # the warning goes away, and plan_warning flags the day if it's now over budget.
        item.reason = "Added back by you. Pick a date that fits your budget."

    if "position" in data:
        rows = sorted((i for i in goal.items if i.id != item.id), key=lambda i: i.position)
        rows.insert(min(data["position"], len(rows)), item)
        for pos, i in enumerate(rows):
            i.position = pos
        item.user_edited = True
    elif "scheduled_date" in data:
        _renumber(goal.id, db, first=None)
    db.commit()
    db.refresh(item)
    return _item_out(item, user, db)


@router.post("/goals/{goal_id}/items", response_model=PlanItemOut, status_code=201)
def add_item(goal_id: str, body: PlanItemCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    goal = _owned_goal(goal_id, user, db)
    _check_date(body.scheduled_date, goal)
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Topic can't be empty.")
    item = PlanItem(
        goal_id=goal.id, owner_id=user.id, position=len(goal.items), scheduled_date=body.scheduled_date,
        topic=topic, concept=None, activity_type=body.activity_type, estimated_minutes=body.estimated_minutes,
        objective="", source_chunk_ids=[], status="pending", user_edited=True, reason="Added by you.",
    )
    goal.items.append(item)
    _renumber(goal.id, db)
    db.commit()
    db.refresh(item)
    return _item_out(item, user, db)


@router.delete("/plan-items/{item_id}", status_code=204)
def delete_item(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = _owned_item(item_id, user, db)
    goal_id = item.goal_id
    db.delete(item)
    _renumber(goal_id, db)
    db.commit()
    return Response(status_code=204)


# ---------- adaptation ----------

@router.post("/goals/{goal_id}/adapt", response_model=PlanProposalOut | None)
def adapt_goal(goal_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    goal = _owned_goal(goal_id, user, db)
    items = [i for i in goal.items if not is_dropped(i)]
    result = adapt(items, _today(), goal.deadline, goal.minutes_per_day, list(goal.study_days or []), _mastery_levels(user, db))
    _supersede_proposals(goal, db)
    if result is None:
        db.commit()
        return None
    p = PlanProposal(goal_id=goal.id, owner_id=user.id, reason=result.reason, changes=result.changes, status="pending")
    db.add(p)
    db.commit()
    db.refresh(p)
    return _proposal_out(p)


def _owned_proposal(pid: str, user: User, db: Session) -> PlanProposal:
    p = db.scalar(select(PlanProposal).where(PlanProposal.id == pid, PlanProposal.owner_id == user.id))
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return p


def _apply_change(goal: Goal, c: dict[str, Any], by_id: dict[str, PlanItem], user: User, db: Session) -> None:
    op = c.get("op")
    item = by_id.get(c.get("item_id") or "")
    to_date = date.fromisoformat(c["to_date"]) if c.get("to_date") else None
    if op == "add" and to_date and c.get("topic"):
        topic = str(c["topic"])[:255]
        related = next((i for i in goal.items if (i.concept or i.topic).casefold() == topic.casefold() and i.source_chunk_ids), None)
        goal.items.append(PlanItem(
            goal_id=goal.id, owner_id=user.id, position=len(goal.items), scheduled_date=to_date, topic=topic,
            concept=topic[:120], activity_type=c.get("activity_type") or "review",
            estimated_minutes=int(c.get("minutes") or 15), objective=f"Quick recall check on {topic}.",
            source_chunk_ids=list(related.source_chunk_ids) if related else [], status="pending",
            user_edited=False, reason=str(c.get("why") or ""),
        ))
        return
    if item is None or item.status != "pending":
        return  # stale change (item edited or removed since the proposal); skip it safely
    if op == "move" and to_date:
        item.scheduled_date = to_date
        item.reason = str(c.get("why") or item.reason)
    elif op == "resize" and c.get("minutes"):
        item.estimated_minutes = int(c["minutes"])
    elif op == "remove":
        goal.items.remove(item)


@router.post("/plan-proposals/{pid}/accept", response_model=GoalOut)
def accept_proposal(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _owned_proposal(pid, user, db)
    goal = _owned_goal(p.goal_id, user, db)
    if p.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"This proposal was already {p.status}.")
    by_id = {i.id: i for i in goal.items}
    for c in p.changes or []:
        _apply_change(goal, c, by_id, user, db)
    p.status = "accepted"
    _renumber(goal.id, db)
    return _commit_out(goal, user, db)


@router.post("/plan-proposals/{pid}/reject", response_model=GoalOut)
def reject_proposal(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _owned_proposal(pid, user, db)
    goal = _owned_goal(p.goal_id, user, db)
    if p.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"This proposal was already {p.status}.")
    p.status = "rejected"
    return _commit_out(goal, user, db)


# ---------- today ----------

@router.get("/today", response_model=TodayOut)
def today_items(user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = _today()
    rows = db.execute(
        select(PlanItem, Goal)
        .join(Goal, Goal.id == PlanItem.goal_id)
        .where(PlanItem.owner_id == user.id, Goal.owner_id == user.id, Goal.status == "active",
               PlanItem.scheduled_date == today, PlanItem.status == "pending")
        .order_by(Goal.created_at, PlanItem.position)
    ).all()
    sources = _source_map({c for i, _ in rows for c in (i.source_chunk_ids or [])}, user, db)
    items = [TodayItem(**_item_dict(i, sources), goal_id=g.id, goal_title=g.title) for i, g in rows]
    return TodayOut(date=today, items=items, total_minutes=sum(i.estimated_minutes for i in items))
