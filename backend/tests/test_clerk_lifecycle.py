"""Account lifecycle with Clerk: webhook signatures, user.deleted / user.updated, deleting an account."""
import base64
import dataclasses
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app import jobs
from app.config import get_settings
from app.db import SessionLocal
from app.jobs import Job
from app.models import Document, User
from app.routers import webhooks as webhooks_router
from app.webhook_signature import InvalidSignature, sign, verify
from tests.test_auth_clerk import bearer

SECRET = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()


# ---------------------------------------------------------------- signatures

def _headers(body: bytes, secret=SECRET, ts=None, msg_id="msg_1", prefix="svix-"):
    ts = int(time.time()) if ts is None else ts
    return {f"{prefix}id": msg_id, f"{prefix}timestamp": str(ts), f"{prefix}signature": sign(secret, msg_id, ts, body)}


def test_signature_accepts_valid_and_rotated_and_standard_names():
    body = b'{"type":"user.updated"}'
    verify(SECRET, _headers(body), body)
    verify(SECRET, _headers(body, prefix="webhook-"), body)
    h = _headers(body)
    h["svix-signature"] = "v1,AAAA " + h["svix-signature"]  # during key rotation several are sent
    verify(SECRET, h, body)


@pytest.mark.parametrize("case", ["tampered", "wrong secret", "old", "future", "missing", "v2 only"])
def test_signature_rejects(case):
    body = b'{"type":"user.deleted","data":{"id":"user_1"}}'
    other = "whsec_" + base64.b64encode(b"another-secret-another-secret-12").decode()
    h = {
        "tampered": _headers(b'{"type":"user.deleted","data":{"id":"user_2"}}'),
        "wrong secret": _headers(body, secret=other),
        "old": _headers(body, ts=int(time.time()) - 600),
        "future": _headers(body, ts=int(time.time()) + 600),
        "missing": {},
        "v2 only": {**_headers(body), "svix-signature": "v2," + _headers(body)["svix-signature"][3:]},
    }[case]
    with pytest.raises(InvalidSignature):
        verify(SECRET, h, body)


# ---------------------------------------------------------------- webhook endpoint

@pytest.fixture
def webhook_on(monkeypatch):
    s = dataclasses.replace(get_settings(), clerk_webhook_signing_secret=SECRET)
    monkeypatch.setattr(webhooks_router, "get_settings", lambda: s)


def _post(client, event: dict, **kw):
    body = json.dumps(event).encode()
    return client.post("/api/webhooks/clerk", content=body, headers={"content-type": "application/json", **_headers(body, **kw)})


def _clerk_user_with_doc(client, fake, clerk_id, sample_pdf):
    fake.add(clerk_id, f"{clerk_id}@example.com")
    doc = client.post("/api/documents?rights_confirmed=true", headers=bearer(clerk_id),
                      files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.external_id == clerk_id))
        key = db.scalar(select(Document.storage_key).where(Document.id == doc["id"]))
    return u.id, os.path.join(get_settings().storage_dir, key)


def test_webhook_is_off_without_a_secret(client):
    assert client.post("/api/webhooks/clerk", content=b"{}").status_code == 404


def test_user_deleted_removes_account_files_and_is_idempotent(client, fake_clerk, webhook_on, sample_pdf):
    uid, path = _clerk_user_with_doc(client, fake_clerk, "user_gone", sample_pdf)
    assert os.path.exists(path)
    event = {"type": "user.deleted", "data": {"id": "user_gone", "deleted": True}}
    assert _post(client, event).status_code == 204
    with SessionLocal() as db:
        assert db.get(User, uid) is None
        assert db.scalar(select(func.count()).select_from(Document).where(Document.owner_id == uid)) == 0
    assert not os.path.exists(path)
    assert _post(client, event, msg_id="msg_retry").status_code == 204  # redelivery is harmless
    assert not [c for c in fake_clerk.calls if c.startswith("DELETE")], "the Clerk user is already gone"


def test_bad_signature_deletes_nothing(client, fake_clerk, webhook_on, sample_pdf):
    uid, _ = _clerk_user_with_doc(client, fake_clerk, "user_safe", sample_pdf)
    body = json.dumps({"type": "user.deleted", "data": {"id": "user_safe"}}).encode()
    h = _headers(body)
    h["svix-signature"] = "v1," + base64.b64encode(b"x" * 32).decode()
    assert client.post("/api/webhooks/clerk", content=body, headers=h).status_code == 401
    with SessionLocal() as db:
        assert db.get(User, uid) is not None


def _updated(clerk_id, email, verified=True):
    return {"type": "user.updated", "data": {
        "id": clerk_id, "primary_email_address_id": "idn_2",
        "email_addresses": [{"id": "idn_2", "email_address": email,
                             "verification": {"status": "verified" if verified else "unverified"}}]}}


def test_user_updated_follows_verified_email_only(client, fake_clerk, webhook_on, sample_pdf):
    uid, _ = _clerk_user_with_doc(client, fake_clerk, "user_mail", sample_pdf)
    assert _post(client, _updated("user_mail", "unverified@example.com", verified=False)).status_code == 204
    with SessionLocal() as db:
        assert db.get(User, uid).email == "user_mail@example.com"
    assert _post(client, _updated("user_mail", "New.Address@example.com")).status_code == 204
    with SessionLocal() as db:
        assert db.get(User, uid).email == "new.address@example.com"


def test_user_updated_never_steals_another_accounts_email(client, fake_clerk, webhook_on, sample_pdf):
    uid, _ = _clerk_user_with_doc(client, fake_clerk, "user_x1", sample_pdf)
    _clerk_user_with_doc(client, fake_clerk, "user_x2", sample_pdf)
    assert _post(client, _updated("user_x1", "user_x2@example.com")).status_code == 204
    with SessionLocal() as db:
        assert db.get(User, uid).email == "user_x1@example.com"


def test_non_json_body_is_400(client, webhook_on):
    body = b"not json"
    assert client.post("/api/webhooks/clerk", content=body, headers=_headers(body)).status_code == 400


# ---------------------------------------------------------------- deleting an account

def test_deleting_an_account_also_deletes_the_clerk_user(client, fake_clerk, sample_pdf):
    uid, path = _clerk_user_with_doc(client, fake_clerk, "user_bye", sample_pdf)
    assert client.delete("/api/auth/me", headers=bearer("user_bye")).status_code == 204
    with SessionLocal() as db:
        assert db.get(User, uid) is None
    assert not os.path.exists(path)
    assert "DELETE /v1/users/user_bye" in fake_clerk.calls and "user_bye" not in fake_clerk.users


def test_clerk_outage_during_deletion_is_retried(client, fake_clerk, sample_pdf, monkeypatch):
    """Our data goes immediately; the Clerk deletion waits in the job queue until Clerk answers."""
    from app import config

    uid, _ = _clerk_user_with_doc(client, fake_clerk, "user_retry", sample_pdf)
    db_jobs = dataclasses.replace(get_settings(), job_backend="db")
    monkeypatch.setattr(config, "get_settings", lambda: db_jobs)  # jobs.dispatch reads it at call time
    fake_clerk.down = True
    assert client.delete("/api/auth/me", headers=bearer("user_retry")).status_code == 204
    with SessionLocal() as db:
        assert db.get(User, uid) is None, "Mindmesh data is deleted without waiting for Clerk"
        assert jobs.run_one(db, "w").status == "queued"  # failed, will retry
        fake_clerk.down = False
        later = datetime.now(timezone.utc) + timedelta(hours=1)
        assert jobs.run_one(db, "w", now=lambda: later).status == "done"
        assert db.scalar(select(func.count()).select_from(Job).where(Job.status != "done")) == 0
    assert "user_retry" not in fake_clerk.users
