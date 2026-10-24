"""Account data export and AI usage (workstream F, CONTRACTS §6).

The export discovers user-owned tables generically: every table registered on
Base.metadata with an `owner_id` column is included, so tables added by other
workstreams are exported without changes here. Deletion lives in
`DELETE /api/auth/me` (FR-003).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.hardening import build_export, export_filename
from ..db import Base, get_db, load_all_models
from ..deps import current_user
from ..models import UsageEvent, User

router = APIRouter(prefix="/account", tags=["account"])


def owned_tables():
    """Tables with an owner_id column, in FK dependency order (parents first)."""
    load_all_models()  # idempotent; makes sure every models_*.py table is registered
    return [t for t in Base.metadata.sorted_tables if "owner_id" in t.c]


@router.get("/export")
def export_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    users = User.__table__
    user_row = db.execute(select(users).where(users.c.id == user.id)).mappings().one()
    tables: dict[str, list] = {}
    for t in owned_tables():
        q = select(t).where(t.c.owner_id == user.id)
        order = [c for c in (t.c.get("created_at"), t.c.get("id")) if c is not None]
        if order:
            q = q.order_by(*order)
        tables[t.name] = [dict(r) for r in db.execute(q).mappings()]
    doc = build_export(user_row, tables, now)
    body = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(now)}"',
            "Cache-Control": "private, no-store",
        },
    )


class TaskUsage(BaseModel):
    task: str
    tokens: int


class UsageOut(BaseModel):
    last_24h_tokens: int
    daily_budget: int  # 0 = unlimited
    by_task: list[TaskUsage]


@router.get("/usage", response_model=UsageOut)
def usage(user: User = Depends(current_user), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=1)
    tokens = func.coalesce(func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), 0)
    rows = db.execute(
        select(UsageEvent.task, tokens.label("tokens"))
        .where(UsageEvent.owner_id == user.id, UsageEvent.created_at >= since)
        .group_by(UsageEvent.task)
        .order_by(tokens.desc())
    ).all()
    by_task = [TaskUsage(task=r.task, tokens=int(r.tokens or 0)) for r in rows]
    return UsageOut(
        last_24h_tokens=sum(t.tokens for t in by_task),
        daily_budget=max(0, get_settings().daily_token_budget),
        by_task=by_task,
    )
