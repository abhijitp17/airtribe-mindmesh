"""Push notifications: device registration, the Expo sender, reminders by push (with or without email)."""
import dataclasses
import json
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{tmp}/t.db", "STORAGE_DIR": tmp, "AI_PROVIDER": "mock"})

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import push  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models_push import PushToken  # noqa: E402

TOK = "ExponentPushToken[abcdefghij1234567890]"


def _settings(monkeypatch, **kw):
    s = dataclasses.replace(get_settings(), **kw)
    for mod in ("app.config", "app.push", "app.services.digests"):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: s)


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]["id"]


@pytest.mark.parametrize("tok, ok", [(TOK, True), ("ExpoPushToken[xyzxyzxyz123]", True), ("abc", False),
                                     ("ExponentPushToken[]", False), ("ExponentPushToken[bad token!]", False)])
def test_token_format(tok, ok):
    assert push.valid_token(tok) is ok


def test_register_is_idempotent_moves_devices_and_can_be_removed(client):
    h1, u1 = _signup(client, "p1@example.com")
    h2, u2 = _signup(client, "p2@example.com")
    body = {"token": TOK, "platform": "ios"}
    assert client.post("/api/me/push-tokens", headers=h1, json=body).status_code == 204
    assert client.post("/api/me/push-tokens", headers=h1, json=body).status_code == 204
    assert client.post("/api/me/push-tokens", headers=h1, json={"token": "nope", "platform": "ios"}).status_code == 422
    assert client.post("/api/me/push-tokens", headers=h2, json={**body, "platform": "android"}).status_code == 204
    with SessionLocal() as db:
        rows = db.scalars(select(PushToken)).all()
        assert [(r.owner_id, r.platform) for r in rows] == [(u2, "android")], "the device now belongs to whoever signed in"
    assert client.request("DELETE", "/api/me/push-tokens", headers=h2, json=body).status_code == 204
    with SessionLocal() as db:
        assert db.scalars(select(PushToken)).all() == []


def test_expo_sender_batches_and_disables_uninstalled_devices(client, monkeypatch):
    _settings(monkeypatch, push_backend="expo", expo_access_token="tok")
    _h, uid = _signup(client, "p3@example.com")
    with SessionLocal() as db:
        for i in range(3):
            db.add(PushToken(owner_id=uid, token=f"ExponentPushToken[device{i}xxxxxxx]", platform="ios"))
        db.commit()
    sent_bodies = []

    def handler(request):
        assert request.headers["authorization"] == "Bearer tok"
        body = json.loads(request.content)
        sent_bodies.append(body)
        data = [{"status": "ok"}, {"status": "error", "details": {"error": "DeviceNotRegistered"}}, {"status": "ok"}][:len(body)]
        return httpx.Response(200, json={"data": data})

    with SessionLocal() as db:
        n = push.send(db, uid, push.PushMessage("T", "B", {"url": "/"}), client=httpx.Client(transport=httpx.MockTransport(handler)))
        assert n == 2 and len(sent_bodies[0]) == 3 and sent_bodies[0][0]["title"] == "T"
        assert len(push.active_tokens(db, uid)) == 2

    def down(request):
        raise httpx.ConnectError("down")
    with SessionLocal() as db, pytest.raises(push.PushError):
        push.send(db, uid, push.PushMessage("T", "B"), client=httpx.Client(transport=httpx.MockTransport(down)))


def test_reminder_goes_out_by_push_when_email_is_off(client, sample_pdf, monkeypatch):
    from tests.test_digests import _local, _user_with_plan_today
    from app.services.digests import run_due

    _settings(monkeypatch, email_backend="off", push_backend="console")
    h, _doc = _user_with_plan_today(client, sample_pdf, email="push@example.com")
    client.post("/api/me/push-tokens", headers=h, json={"token": TOK, "platform": "android"})
    assert run_due(_local(18, 30))["reminder"] == 1
    assert run_due(_local(19, 0))["reminder"] == 0, "once per day across email and push"
