"""Postgres-only checks: migrations + sql/rls.sql actually isolate users at the database.

Skipped unless MINDMESH_PG_URL points at a Postgres database that has already had
`alembic upgrade head` and `sql/rls.sql` applied, connecting as the app role (a table
owner that is NOT a superuser; superusers bypass RLS). Run it in its own process,
because app.db builds one engine per process:

    MINDMESH_PG_URL=postgresql+psycopg://mindmesh:mindmesh@localhost:5432/mindmesh \
        pytest -q tests/test_postgres_rls.py

Uses JOB_BACKEND=db, so ingestion goes through the worker path (SKIP LOCKED + the
system RLS bypass), as it does under docker compose.
"""
import os
import sys
import tempfile
import time
import uuid

import pytest

PG_URL = os.environ.get("MINDMESH_PG_URL", "")
if not PG_URL:
    pytest.skip("MINDMESH_PG_URL not set", allow_module_level=True)
if "app.db" in sys.modules:
    pytest.skip("app.db already bound to another database; run this file on its own", allow_module_level=True)

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": PG_URL,
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
    "JOB_BACKEND": "db",
})

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from app import jobs  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def pg_client():
    # Named pg_client so conftest's _fresh_db (drop_all/create_all) never runs here:
    # recreating tables would silently remove the RLS policies under test.
    with TestClient(app) as c:
        yield c


def _email(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}@example.com"


def _signup(client, tag):
    r = client.post("/api/auth/signup", json={"email": _email(tag), "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    return h, client.get("/api/auth/me", headers=h).json()["id"]


def _drain_jobs() -> None:
    db = SessionLocal()
    try:
        while jobs.run_one(db, "test-worker") is not None:
            pass
    finally:
        db.close()


def _upload(client, headers, pdf):
    r = client.post("/api/documents?rights_confirmed=true", headers=headers,
                    files={"file": ("fp.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    for _ in range(50):
        _drain_jobs()
        d = client.get(f"/api/documents/{doc_id}", headers=headers).json()
        if d["status"] not in ("uploaded", "processing"):
            return d
        time.sleep(0.05)
    raise AssertionError("processing did not finish")


def _scalar(sql: str, user_id: str | None = None, bypass: bool = False, **params):
    """Run one query as the app role, in its own transaction, scoped like the app would be."""
    with engine.connect() as conn, conn.begin():
        if user_id:
            conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": user_id})
        if bypass:
            conn.execute(text("SELECT set_config('app.rls_bypass', 'on', true)"))
        return conn.execute(text(sql), params).scalar()


def _rows(sql: str, user_id: str | None = None, **params):
    with engine.connect() as conn, conn.begin():
        if user_id:
            conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": user_id})
        return conn.execute(text(sql), params).all()


def test_app_role_cannot_bypass_rls():
    # A superuser or BYPASSRLS role makes every policy a no-op.
    row = _scalar("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
    assert row is False, "app connects as a superuser/BYPASSRLS role: RLS is not enforced"


def test_every_owner_table_has_forced_rls():
    missing = _scalar("""
        SELECT string_agg(c.relname, ', ')
        FROM pg_class c
        JOIN information_schema.columns col
          ON col.table_name = c.relname AND col.table_schema = current_schema() AND col.column_name = 'owner_id'
        WHERE c.relkind = 'r' AND c.relnamespace = current_schema()::regnamespace
          AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
    """)
    assert missing is None, f"RLS not enabled+forced on: {missing} (run sql/rls.sql)"


def test_learning_loop_and_isolation_under_rls(pg_client, sample_pdf, monkeypatch):
    owner, owner_id = _signup(pg_client, "owner")
    intruder, intruder_id = _signup(pg_client, "intruder")

    # The full loop works with RLS on: the per-transaction app.user_id hook is wired correctly.
    assert pg_client.get("/api/me/prefs", headers=owner).status_code == 200
    doc = _upload(pg_client, owner, sample_pdf)
    assert doc["status"] == "ready" and doc["page_count"] == 2, doc
    # The concept extraction job (system context) wrote the document's graph edges; the owner reads them.
    assert pg_client.get(f"/api/documents/{doc['id']}/concepts", headers=owner).json()
    ans = pg_client.post("/api/tutor/ask", headers=owner,
                         json={"question": "What is Little's Law?", "document_ids": [doc["id"]]}).json()
    assert ans["status"] == "verified"
    quiz = pg_client.post("/api/quizzes", headers=owner, json={"document_ids": [doc["id"]], "count": 3}).json()
    q = quiz["questions"][0]
    body = {"selected_index": 0} if q["qtype"] == "mcq" else {"answer_text": "I don't know"}
    assert pg_client.post(f"/api/questions/{q['id']}/attempts", headers=owner, json=body).status_code == 201
    assert pg_client.get("/api/progress", headers=owner).json()["totals"]["attempts"] == 1

    # App layer: other users get 404.
    assert pg_client.get(f"/api/documents/{doc['id']}", headers=intruder).status_code == 404
    assert pg_client.get(f"/api/documents/{doc['id']}/concepts", headers=intruder).status_code == 404
    assert pg_client.get("/api/documents", headers=intruder).json() == []

    # Database layer: rows are invisible without the owner's id, even with a raw query.
    q_doc = "SELECT count(*) FROM documents WHERE id = :d"
    assert _scalar(q_doc, d=doc["id"]) == 0, "no app.user_id set must see nothing (fail closed)"
    assert _scalar(q_doc, user_id=intruder_id, d=doc["id"]) == 0
    assert _scalar(q_doc, user_id=owner_id, d=doc["id"]) == 1
    assert _scalar("SELECT count(*) FROM chunks WHERE document_id = :d", user_id=intruder_id, d=doc["id"]) == 0
    # Product events were written under the owner's scope (the learning path activated) and stay private.
    q_ev = "SELECT count(*) FROM product_events WHERE owner_id = :o AND name = :n"
    assert _scalar(q_ev, user_id=owner_id, o=owner_id, n="activated") == 1
    assert _scalar(q_ev, user_id=intruder_id, o=owner_id, n="question_answered") == 0
    # The retention purge (system context) sees every user's rows.
    import dataclasses
    from datetime import datetime, timedelta, timezone

    from app.config import get_settings
    from app.services import retention

    monkeypatch.setattr(retention, "get_settings",
                        lambda: dataclasses.replace(get_settings(), retention_events_days=1, retention_jobs_days=0))
    assert retention.run_purge(datetime.now(timezone.utc) + timedelta(days=2), dry_run=True)["events"] >= 4

    # Writes: the intruder can neither change the owner's rows nor plant rows under the owner's id.
    changed = _scalar("WITH u AS (UPDATE documents SET title = 'pwned' WHERE id = :d RETURNING 1) "
                      "SELECT count(*) FROM u", user_id=intruder_id, d=doc["id"])
    assert changed == 0
    with pytest.raises(DBAPIError, match="row-level security"):
        _scalar("INSERT INTO usage_events (id, owner_id, task, model, input_tokens, output_tokens, "
                "latency_ms, prompt_version, created_at) VALUES (:i, :o, 't', 'm', 0, 0, 0, 'v', now()) "
                "RETURNING 1", user_id=intruder_id, i=uuid.uuid4().hex, o=owner_id)


def test_account_deletion_cascades_under_rls(pg_client, sample_pdf):
    h, uid = _signup(pg_client, "leaver")
    _upload(pg_client, h, sample_pdf)
    assert _scalar("SELECT count(*) FROM chunks WHERE owner_id = :u", bypass=True, u=uid) > 0
    assert pg_client.delete("/api/auth/me", headers=h).status_code == 204
    for table in ("documents", "chunks", "user_prefs"):
        assert _scalar(f"SELECT count(*) FROM {table} WHERE owner_id = :u", bypass=True, u=uid) == 0, table


def test_knowledge_graph_under_rls(pg_client):
    """kg_* tables are RLS-covered and the recursive prerequisite query works on Postgres."""
    from app.core.planner import TopicSpec
    from app.services.knowledge_graph import prerequisite_chain, record_prerequisites

    _owner, owner_id = _signup(pg_client, "kg-owner")
    _intruder, intruder_id = _signup(pg_client, "kg-intruder")
    topics = [TopicSpec(topic="Basics", concept="Flow basics"),
              TopicSpec(topic="Little", concept="Little's Law", prerequisites=["Basics"]),
              TopicSpec(topic="Queues", concept="Queueing", prerequisites=["Little"])]
    db = SessionLocal()
    db.info["user_id"] = owner_id  # what deps.current_user does; the hook scopes RLS to it
    try:
        assert record_prerequisites(db, owner_id, topics, {"goal_id": "g"}) == 2
        db.commit()
        assert prerequisite_chain(db, owner_id, "Queueing") == [("Little's Law", 1), ("Flow basics", 2)]
    finally:
        db.close()
    assert _scalar("SELECT count(*) FROM kg_edges WHERE owner_id = :o", user_id=intruder_id, o=owner_id) == 0
    assert _scalar("SELECT count(*) FROM kg_nodes WHERE owner_id = :o", o=owner_id) == 0  # no app.user_id: fail closed
    assert _scalar("SELECT count(*) FROM kg_edges WHERE owner_id = :o", user_id=owner_id, o=owner_id) == 2


def test_clerk_mode_first_request_is_rls_scoped(pg_client, sample_pdf, monkeypatch):
    """In Clerk mode the user lookup runs before the user id is known; the request's later
    queries must still run in a transaction scoped to that user, or RLS hides their rows."""
    import dataclasses

    import httpx

    from app import clerk as clerk_mod
    from app import deps
    from app.clerk import ClerkAPI, ClerkVerifier
    from app.config import get_settings
    from tests.test_auth_clerk import FakeClerk
    from tests.test_clerk_verify import ISS, PUBLIC_PEM, WEB, token

    settings = dataclasses.replace(get_settings(), auth_provider="clerk", clerk_frontend_api_url=ISS,
                                   clerk_authorized_parties=[WEB], clerk_secret_key="sk_test_fake")
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(clerk_mod, "get_verifier", lambda: ClerkVerifier(ISS, [WEB], pem=PUBLIC_PEM))
    fake = FakeClerk()
    cid = f"user_pg_{uuid.uuid4().hex[:8]}"
    fake.add(cid, f"{cid}@example.com")
    clerk_mod.set_api(ClerkAPI("sk_test_fake", "https://api.clerk.test/v1", transport=httpx.MockTransport(fake.handler)))
    try:
        h = {"Authorization": f"Bearer {token(sub=cid)}"}
        doc = _upload(pg_client, h, sample_pdf)  # first request provisions the user, then writes under RLS
        assert doc["status"] == "ready"
        assert [d["id"] for d in pg_client.get("/api/documents", headers=h).json()] == [doc["id"]]
    finally:
        clerk_mod.set_api(None)


def test_reminder_emails_work_under_rls(pg_client, sample_pdf, monkeypatch):
    """run_due reads every opted-in user and writes email_log (an RLS table) as system work."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    from app.services import digests

    sent = []
    monkeypatch.setattr(digests, "send", lambda e: sent.append(e) or True)
    h, _uid = _signup(pg_client, "remind")
    h = {**h, "X-Timezone": "Asia/Kolkata"}
    pg_client.get("/api/me/prefs", headers=h)
    pg_client.patch("/api/me/prefs", headers=h, json={"reminders": True})
    doc = _upload(pg_client, h, sample_pdf)
    kol = ZoneInfo("Asia/Kolkata")
    deadline = (datetime.now(kol).date() + timedelta(days=14)).isoformat()
    assert pg_client.post("/api/goals", headers=h, json={
        "goal_type": "learn", "title": "Plan", "deadline": deadline, "minutes_per_day": 30,
        "study_days": list(range(7)), "document_ids": [doc["id"]]}).status_code == 201
    evening = datetime.now(kol).replace(hour=18, minute=30, second=0, microsecond=0).astimezone(timezone.utc)
    first = digests.run_due(evening)
    again = digests.run_due(evening + timedelta(minutes=5))
    # the reminder only: on a Monday the weekly summary goes out too
    mine = [e for e in sent if e.to.startswith("remind-") and e.subject == "Your Mindmesh session for today"]
    assert len(mine) == 1 and first["reminder"] >= 1 and again["reminder"] == 0


def test_pgvector_nearest_neighbours_under_rls(pg_client, sample_pdf, monkeypatch):
    """Needs `python -m app.tools.pgvector_setup --dim 128` (CI does it; skipped where pgvector isn't installed)."""
    import dataclasses

    from sqlalchemy import inspect

    from app.config import get_settings
    from app.services import embeddings_store as store

    if not any(c["name"] == "embedding_vec" for c in inspect(engine).get_columns("chunk_embeddings")):
        pytest.skip("pgvector column not set up (python -m app.tools.pgvector_setup --dim 128)")
    s = dataclasses.replace(get_settings(), dense_embedder="fake")
    for mod in ("app.config", "app.services.ingestion", "app.services.learning"):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: s)
    store._pgvector_ready.clear()
    owner, owner_id = _signup(pg_client, "vec-owner")
    _intruder, intruder_id = _signup(pg_client, "vec-intruder")
    doc = _upload(pg_client, owner, sample_pdf)
    assert _scalar("SELECT count(*) FROM chunk_embeddings WHERE document_id = :d AND embedding_vec IS NOT NULL",
                   user_id=owner_id, d=doc["id"]) > 0
    ids = [r[0] for r in _rows("SELECT id FROM chunks WHERE document_id = :d", user_id=owner_id, d=doc["id"])]
    with SessionLocal() as db:
        db.info["user_id"] = owner_id
        got = store.dense_scores(db, owner_id, ids, "What is Little's Law?")
        assert got and set(got) <= set(ids)
    with SessionLocal() as db:
        db.info["user_id"] = intruder_id  # RLS hides the owner's vectors even with their ids
        assert store.dense_scores(db, owner_id, ids, "What is Little's Law?") is None
    ans = pg_client.post("/api/tutor/ask", headers=owner, json={"question": "What is Little's Law?", "document_ids": [doc["id"]]})
    assert ans.json()["status"] == "verified"


def test_periodic_leader_is_exclusive_across_workers():
    with jobs.leader("test-task") as first:
        with jobs.leader("test-task") as second:  # another connection = another worker
            assert first is True and second is False
        with jobs.leader("other-task") as other:
            assert other is True
    with jobs.leader("test-task") as again:
        assert again is True, "released after the task"
