from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_is_sqlite = _settings.database_url.startswith("sqlite")
# Pool per API process. Size it to the threadpool: FastAPI runs sync routes on up to 40 threads.
# A short timeout fails fast with a 503 (see main.py) instead of hanging requests for 30 s.
_pool = {} if _is_sqlite else {
    "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
    "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
    "pool_timeout": float(os.getenv("DB_POOL_TIMEOUT", "10")),
}
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    **_pool,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_fk(dbapi_conn, _):  # enforce ON DELETE CASCADE in SQLite
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Session, "after_flush")
def _mark_writes(session, _ctx):
    session.info["has_writes"] = True


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_soft_rollback")
def _clear_writes(session, *_):
    session.info.pop("has_writes", None)


def release_if_idle(session: Session) -> None:
    """Give the DB connection back to the pool before a slow call (an AI model call takes seconds).

    Only a read-only transaction is ended (commit: nothing to write, and loaded objects stay
    usable because expire_on_commit=False). A transaction that has written keeps its connection,
    so a route that writes and then calls the model stays atomic.
    """
    if session.in_transaction() and not session.info.get("has_writes") and not (session.new or session.dirty or session.deleted):
        session.commit()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def load_all_models() -> None:
    """Import every `app/models*.py` so all tables are registered on Base.metadata.

    Workstreams add tables in their own models_<feature>.py; nothing else to wire.
    """
    import importlib
    import pkgutil
    from pathlib import Path

    for m in sorted(pkgutil.iter_modules([str(Path(__file__).parent)]), key=lambda m: m.name):
        if m.name == "models" or m.name.startswith("models_"):
            importlib.import_module(f"{__package__}.{m.name}")


def init_db() -> None:
    load_all_models()
    Base.metadata.create_all(engine)
