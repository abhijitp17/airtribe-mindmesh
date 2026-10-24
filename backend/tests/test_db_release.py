"""Releasing the DB connection before slow model calls (app/db.py release_if_idle, Gateway.before_call)."""
from sqlalchemy import select

from app.ai.gateway import Gateway, Request
from app.ai.mock import MockProvider
from app.db import SessionLocal, release_if_idle
from app.models import User


def test_read_only_transaction_is_released_and_objects_stay_usable(client):
    db = SessionLocal()
    try:
        db.add(User(email="reader@example.com", password_hash=None))
        db.commit()
        u = db.scalar(select(User).where(User.email == "reader@example.com"))
        assert db.in_transaction()
        release_if_idle(db)
        assert not db.in_transaction(), "connection goes back to the pool"
        assert u.email == "reader@example.com", "loaded objects are not expired"
    finally:
        db.close()


def test_pending_or_flushed_writes_keep_the_transaction(client):
    db = SessionLocal()
    try:
        db.add(User(email="pending@example.com", password_hash=None))
        release_if_idle(db)
        assert db.new, "pending writes are untouched"
        db.flush()
        release_if_idle(db)
        assert db.in_transaction(), "a transaction that wrote stays open: the route stays atomic"
        db.rollback()
        assert db.scalar(select(User).where(User.email == "pending@example.com")) is None
    finally:
        db.close()


def test_gateway_runs_before_call_before_each_model_call():
    calls = []
    gw = Gateway(MockProvider(), "m", "f", before_call=lambda: calls.append("released"))
    gw.complete(Request(task="answerable", system="s", user="u", context={"question": "q", "sources": []}))
    assert calls == ["released"]
