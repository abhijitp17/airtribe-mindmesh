"""Retention purge: off by default, minimums, only finished jobs, dry run, batches."""
import dataclasses
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_retention.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.jobs import Job  # noqa: E402
from app.models import UsageEvent, User  # noqa: E402
from app.models_analytics import ProductEvent  # noqa: E402
from app.models_engagement import EmailLog  # noqa: E402
from app.services import retention  # noqa: E402

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _ago(days):
    return NOW - timedelta(days=days)


@pytest.fixture
def seeded(client):  # `client` gives a fresh database
    with SessionLocal() as db:
        u = User(email="r@example.com", password_hash="x", display_name="")
        db.add(u)
        db.flush()
        for d in (1, 5, 10, 100, 400):
            db.add(EmailLog(owner_id=u.id, kind=f"k{d}", local_date=date(2026, 1, 1) + timedelta(days=d), sent_at=_ago(d)))
            db.add(UsageEvent(owner_id=u.id, task="tutor", model="m", input_tokens=1, output_tokens=1, latency_ms=1,
                              prompt_version="v", created_at=_ago(d)))
            db.add(ProductEvent(owner_id=u.id, name="signed_up", props={}, created_at=_ago(d)))
        for status in ("done", "failed", "queued", "running"):
            db.add(Job(kind="ingest_document", payload={}, status=status, attempts=0, max_attempts=3,
                       run_after=_ago(90), created_at=_ago(90), updated_at=_ago(90)))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(Job))
        db.commit()


def _settings(monkeypatch, **days):
    s = dataclasses.replace(get_settings(), **days)
    monkeypatch.setattr(retention, "get_settings", lambda: s)


def _count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_effective_days():
    assert retention.effective_days(0, 8) == 0 and retention.effective_days(-5, 8) == 0
    assert retention.effective_days(3, 8) == 8 and retention.effective_days(90, 8) == 90


def test_legal_periods_keep_everything_by_default(seeded, monkeypatch):
    _settings(monkeypatch, retention_jobs_days=0)
    assert retention.run_purge(NOW) == {}
    assert (_count(EmailLog), _count(UsageEvent), _count(ProductEvent), _count(Job)) == (5, 5, 5, 4)


def test_default_settings_purge_only_old_finished_jobs(seeded, monkeypatch):
    _settings(monkeypatch)  # defaults: jobs 30 days, the rest keep
    assert retention.run_purge(NOW) == {"jobs": 2}
    with SessionLocal() as db:
        assert sorted(db.scalars(select(Job.status))) == ["queued", "running"]


def test_periods_and_minimums(seeded, monkeypatch, caplog):
    _settings(monkeypatch, retention_email_log_days=3, retention_usage_days=30, retention_events_days=365,
              retention_jobs_days=0)
    got = retention.run_purge(NOW)
    # email log: 3 days asked, raised to 8 -> rows at 10, 100, 400 days go
    assert got == {"email_log": 3, "usage": 2, "events": 1}
    assert (_count(EmailLog), _count(UsageEvent), _count(ProductEvent)) == (2, 3, 4)
    assert "raised from 3 to 8 days" in caplog.text


def test_dry_run_deletes_nothing(seeded, monkeypatch):
    _settings(monkeypatch, retention_usage_days=30)
    assert retention.run_purge(NOW, dry_run=True)["usage"] == 2
    assert _count(UsageEvent) == 5


def test_batches(seeded, monkeypatch):
    _settings(monkeypatch, retention_usage_days=2, retention_jobs_days=0)
    monkeypatch.setattr(retention, "BATCH", 1)
    assert retention.run_purge(NOW)["usage"] == 4
    assert retention.run_purge(NOW)["usage"] == 0  # idempotent


def test_cli(seeded, monkeypatch, capsys):
    from app.tools import purge

    _settings(monkeypatch, retention_usage_days=30)
    assert purge.main(["--dry-run"]) == 0
    assert "usage: would delete" in capsys.readouterr().out
