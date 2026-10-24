"""Retention purge jobs (docs/legal/retention-policy.md).

Each kind of operational record has a retention period from settings, in days. 0 means
"keep" — the default for the periods that are still a legal [DECISION] — so nothing is
purged until someone chooses a period. Periods shorter than what the product itself needs
are raised to that minimum (and logged), so a typo can't break budgets or idempotency:

  email_log   >= 8 days   (one-email-per-day and the weekly summary read recent rows)
  usage       >= 2 days   (the daily AI budget sums the last 24 hours)
  jobs        >= 1 day    (finished jobs only; queued/running are never touched)
  events      >= 1 day    (product analytics; experiment reports read the window you keep)

Finished job rows default to 30 days: their payloads can carry identifiers (a deleted
account's Clerk id), so keeping them forever is the worse default.

Runs from worker.py (hourly by default) or `python -m app.tools.purge [--dry-run]`.
Deletes in batches so a first run on a big table doesn't hold long locks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings

log = logging.getLogger("mindmesh.retention")
BATCH = 5000


@dataclass(frozen=True)
class Target:
    name: str
    model: Callable[[], Any]  # lazy: the model class
    column: str  # timestamp the age is measured from
    days: Callable[[Any], int]  # settings -> configured days (0 = keep)
    minimum: int
    extra: Callable[[Any], list] = lambda m: []  # extra WHERE clauses


def _targets() -> list[Target]:
    def email_log():
        from ..models_engagement import EmailLog
        return EmailLog

    def usage():
        from ..models import UsageEvent
        return UsageEvent

    def jobs():
        from ..jobs import Job
        return Job

    def events():
        from ..models_analytics import ProductEvent
        return ProductEvent

    return [
        Target("email_log", email_log, "sent_at", lambda s: s.retention_email_log_days, 8),
        Target("usage", usage, "created_at", lambda s: s.retention_usage_days, 2),
        Target("jobs", jobs, "updated_at", lambda s: s.retention_jobs_days, 1,
               extra=lambda m: [m.status.in_(("done", "failed"))]),
        Target("events", events, "created_at", lambda s: s.retention_events_days, 1),
    ]


def effective_days(configured: int, minimum: int) -> int:
    """0 (or less) keeps everything; otherwise at least the minimum the product needs."""
    if configured <= 0:
        return 0
    return max(configured, minimum)


def run_purge(now: datetime | None = None, dry_run: bool = False, db: Session | None = None) -> dict[str, int]:
    """Delete records older than their retention period. Returns {target: rows (that would be) deleted}."""
    from ..jobs import system_context

    s = get_settings()
    now = now or datetime.now(timezone.utc)
    out: dict[str, int] = {}
    with system_context():  # every user's rows (RLS bypass for trusted server code)
        own = db is None
        if own:
            from ..db import SessionLocal
            db = SessionLocal()
        try:
            for t in _targets():
                configured = t.days(s)
                days = effective_days(configured, t.minimum)
                if days == 0:
                    continue
                if days != configured:
                    log.warning("retention for %s raised from %d to %d days (product minimum)", t.name, configured, days)
                model = t.model()
                col = getattr(model, t.column)
                where = [col < now - timedelta(days=days), *t.extra(model)]
                if dry_run:
                    out[t.name] = db.scalar(select(func.count()).select_from(model).where(*where)) or 0
                    continue
                total = 0
                while True:
                    ids = db.scalars(select(model.id).where(*where).limit(BATCH)).all()
                    if not ids:
                        break
                    db.execute(delete(model).where(model.id.in_(ids)))
                    db.commit()
                    total += len(ids)
                out[t.name] = total
                if total:
                    log.info("purged %d %s rows older than %d days", total, t.name, days)
        finally:
            if own:
                db.close()
    return out
