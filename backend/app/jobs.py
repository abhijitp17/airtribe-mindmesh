"""Durable DB-backed job queue (workstream F).

`JOB_BACKEND=inline` (default) keeps today's behaviour: work runs in a FastAPI
BackgroundTask in the API process. `JOB_BACKEND=db` writes a row to `jobs`
and a separate `python worker.py` process claims and runs it, so a crash or
deploy mid-ingestion doesn't lose work.

Semantics: at-least-once. Handlers must be idempotent (process_document is:
it replaces the document's chunks). A job is retried with exponential backoff
until `max_attempts`, then marked `failed` with `last_error`. A worker that
dies mid-job leaves the row `running`; `recover_stale()` requeues it after
`stale_after` (the attempt still counts).

Jobs are system rows (no owner_id); payloads carry ids only, never content.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import traceback
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, select, update
from sqlalchemy.orm import Mapped, Session, aliased, mapped_column

from .core.hardening import next_run_after
from .db import Base

log = logging.getLogger("mindmesh.jobs")

STATUSES = ("queued", "running", "done", "failed")
STALE_AFTER = timedelta(minutes=15)


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)


# ---------------------------------------------------------------- RLS system context

# True while trusted background work (job handlers) runs. The Postgres RLS hook in
# deps.py reads it to set app.rls_bypass for that work's transactions (sql/rls.sql).
rls_system: contextvars.ContextVar[bool] = contextvars.ContextVar("rls_system", default=False)


@contextlib.contextmanager
def system_context():
    token = rls_system.set(True)
    try:
        yield
    finally:
        rls_system.reset(token)


def _as_system(fn: Callable[[dict[str, Any]], None], payload: dict[str, Any]) -> None:
    with system_context():
        fn(payload)


# ---------------------------------------------------------------- pure helpers

def _short_error(exc: BaseException, limit: int = 4000) -> str:
    s = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return s[:limit]


# ---------------------------------------------------------------- registry

Handler = Callable[[dict[str, Any]], None]
_HANDLERS: dict[str, Handler] = {}


def register(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        if kind in _HANDLERS and _HANDLERS[kind] is not fn:
            raise ValueError(f"job kind {kind!r} already registered")
        _HANDLERS[kind] = fn
        return fn

    return deco


def handler_for(kind: str) -> Handler | None:
    return _HANDLERS.get(kind)


@register("ingest_document")
def _ingest_document(payload: dict[str, Any]) -> None:
    from .services.ingestion import process_document  # lazy: avoid import cycles at model load

    process_document(str(payload["document_id"]))


@register("extract_concepts")
def _extract_concepts(payload: dict[str, Any]) -> None:
    from .services.concepts import extract_for_document

    extract_for_document(str(payload["document_id"]))


@register("rebuild_graph")
def _rebuild_graph(payload: dict[str, Any]) -> None:
    from .services.graph import rebuild_graph

    rebuild_graph(str(payload["owner_id"]))


@register("embed_document")
def _embed_document(payload: dict[str, Any]) -> None:
    from .services.embeddings_store import embed_document

    embed_document(str(payload["document_id"]))


@register("delete_clerk_user")
def _delete_clerk_user(payload: dict[str, Any]) -> None:
    """After a Mindmesh account is deleted, remove the Clerk identity too (404 = already gone)."""
    from .clerk import get_api

    get_api().delete_user(str(payload["clerk_id"]))


# ---------------------------------------------------------------- queue operations

def enqueue(db: Session, kind: str, payload: dict[str, Any], max_attempts: int = 3, *, commit: bool = True) -> Job:
    if kind not in _HANDLERS:
        raise ValueError(f"unknown job kind {kind!r}")
    job = Job(kind=kind, payload=dict(payload), status="queued", attempts=0,
              max_attempts=max(1, int(max_attempts)), run_after=_now())
    db.add(job)
    if commit:
        db.commit()
    else:
        db.flush()
    return job


def claim_next(db: Session, worker_id: str, now: datetime | None = None) -> Job | None:
    """Atomically move the oldest due queued job to running and return it (committed)."""
    now = now or _now()
    dialect = db.get_bind().dialect.name
    due = (Job.status == "queued", Job.run_after <= now)
    if dialect == "postgresql":
        job = db.scalars(
            select(Job).where(*due).order_by(Job.run_after, Job.created_at)
            .limit(1).with_for_update(skip_locked=True)
        ).first()
        if job is None:
            db.rollback()
            return None
        job.status, job.locked_at, job.locked_by = "running", now, worker_id
        job.attempts += 1
        job.updated_at = now
        db.commit()
        return job

    # SQLite (and others): one atomic UPDATE ... WHERE id = (SELECT ...) AND status = 'queued'.
    # SQLite serialises writers, so two workers can never both flip the same row; the
    # loser simply updates 0 rows. The winner finds its row via locked_by (worker ids
    # are unique per process and a worker holds at most one job at a time).
    # The subquery uses an alias so SQLAlchemy doesn't auto-correlate it to the UPDATE target.
    j2 = aliased(Job)
    sub = (
        select(j2.id).where(j2.status == "queued", j2.run_after <= now)
        .order_by(j2.run_after, j2.created_at).limit(1).scalar_subquery()
    )
    res = db.execute(
        update(Job)
        .where(Job.id == sub, Job.status == "queued")
        .values(status="running", locked_at=now, locked_by=worker_id,
                attempts=Job.attempts + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    claimed = res.rowcount == 1  # read before commit closes the cursor
    db.commit()
    if not claimed:
        return None
    return db.scalars(
        select(Job).where(Job.status == "running", Job.locked_by == worker_id)
        .order_by(Job.locked_at.desc()).limit(1)
        .execution_options(populate_existing=True)
    ).first()


def recover_stale(db: Session, stale_after: timedelta = STALE_AFTER, now: datetime | None = None) -> int:
    """Requeue jobs whose worker died (running and locked longer than `stale_after`).

    Jobs that already used all attempts are marked failed instead.
    """
    now = now or _now()
    cutoff = now - stale_after
    stale = (Job.status == "running", Job.locked_at < cutoff)
    failed = db.execute(
        update(Job).where(*stale, Job.attempts >= Job.max_attempts)
        .values(status="failed", locked_at=None, locked_by=None, updated_at=now,
                last_error="Worker lost while running (stale lock); attempts exhausted.")
        .execution_options(synchronize_session=False)
    ).rowcount
    requeued = db.execute(
        update(Job).where(*stale)
        .values(status="queued", locked_at=None, locked_by=None, run_after=now, updated_at=now,
                last_error="Worker lost while running (stale lock); requeued.")
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    if failed or requeued:
        log.warning("stale jobs: %d requeued, %d failed", requeued, failed)
    return (requeued or 0) + (failed or 0)


def run_one(db: Session, worker_id: str, now: Callable[[], datetime] = _now) -> Job | None:
    """Claim and run a single job. Returns the job (final state) or None if the queue is empty."""
    job = claim_next(db, worker_id, now())
    if job is None:
        return None
    fn = handler_for(job.kind)
    log.info("job %s kind=%s attempt=%d/%d", job.id, job.kind, job.attempts, job.max_attempts)
    try:
        if fn is None:
            raise LookupError(f"no handler registered for {job.kind!r}")
        _as_system(fn, dict(job.payload or {}))
    except Exception as exc:  # noqa: BLE001 - every failure is recorded on the row
        db.rollback()
        t = now()
        job.last_error = _short_error(exc)
        job.locked_at, job.locked_by, job.updated_at = None, None, t
        if job.attempts >= job.max_attempts or fn is None:
            job.status = "failed"
            log.error("job %s failed permanently: %s", job.id, job.last_error)
            _metric(job.kind, "failed")
        else:
            job.status = "queued"
            job.run_after = next_run_after(job.attempts, t, jitter=0.25)
            log.warning("job %s failed (attempt %d), retry at %s", job.id, job.attempts, job.run_after.isoformat())
            _metric(job.kind, "retry")
        db.commit()
        return job
    t = now()
    job.status, job.locked_at, job.locked_by, job.updated_at = "done", None, None, t
    _metric(job.kind, "done")
    job.last_error = None
    db.commit()
    return job


def _metric(kind: str, outcome: str) -> None:
    from .metrics import record_job

    record_job(kind, outcome)


# ---------------------------------------------------------------- follow-up work from inside a job

def chain(kind: str, payload: dict[str, Any], max_attempts: int = 3) -> None:
    """Start follow-up work from a job handler: a queued row (db backend), or run it now (inline:
    already in the background, after the user-visible work is committed). Never raises."""
    from .config import get_settings

    fn = handler_for(kind)
    if fn is None:
        raise ValueError(f"unknown job kind {kind!r}")
    try:
        if get_settings().job_backend == "db":
            from .db import SessionLocal

            s = SessionLocal()
            try:
                enqueue(s, kind, payload, max_attempts)
            finally:
                s.close()
        else:
            _as_system(fn, dict(payload))
    except Exception:  # noqa: BLE001 - follow-up work must never fail the job that started it
        log.exception("follow-up job %s failed", kind)


# ---------------------------------------------------------------- API-side dispatch

def dispatch(kind: str, payload: dict[str, Any], background_tasks: Any, db: Session | None = None,
             max_attempts: int = 3) -> None:
    """Run `kind` per settings.job_backend.

    inline: schedule on FastAPI BackgroundTasks (runs after the response, in-process).
    db:     enqueue a row for worker.py; uses `db` if given, else a short-lived session.
    """
    from .config import get_settings

    fn = handler_for(kind)
    if fn is None:
        raise ValueError(f"unknown job kind {kind!r}")
    if get_settings().job_backend == "db":
        if db is not None:
            enqueue(db, kind, payload, max_attempts)
            return
        from .db import SessionLocal

        s = SessionLocal()
        try:
            enqueue(s, kind, payload, max_attempts)
        finally:
            s.close()
        return
    background_tasks.add_task(_as_system, fn, dict(payload))




# ---------------------------------------------------------------- leader election for periodic work

@contextlib.contextmanager
def leader(name: str):
    """Yields True for exactly one worker at a time per `name` (Postgres session advisory lock), so
    periodic tasks don't run on every worker at once. SQLite (dev, one process): always True."""
    from sqlalchemy import text

    from .db import engine

    if engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as conn:
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(hashtext(:n))"), {"n": f"mindmesh:{name}"}).scalar())
        try:
            yield got
        finally:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(hashtext(:n))"), {"n": f"mindmesh:{name}"})
            conn.commit()
