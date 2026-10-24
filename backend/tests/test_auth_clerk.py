"""AUTH_PROVIDER=clerk: token -> user mapping, provisioning and account linking (no network).

The `client` and `fake_clerk` fixtures live in conftest.py; FakeClerk is defined here.
"""
import time

import httpx
import pytest
from sqlalchemy import select

from app import deps
from app.db import SessionLocal
from app.models import User
from app.security import hash_password
from tests.test_clerk_verify import token


class FakeClerk:
    """Clerk Backend API: GET/DELETE /users/{id}. Counts calls; can be switched to fail."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.calls: list[str] = []
        self.down = False

    def add(self, clerk_id, email, verified=True, first_name="Priya"):
        self.users[clerk_id] = {
            "id": clerk_id, "first_name": first_name, "primary_email_address_id": "idn_1",
            "email_addresses": [{"id": "idn_1", "email_address": email,
                                 "verification": {"status": "verified" if verified else "unverified"}}],
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        assert request.headers["authorization"] == "Bearer sk_test_fake"
        if self.down:
            return httpx.Response(500)
        uid = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            return httpx.Response(200, json=self.users[uid]) if uid in self.users else httpx.Response(404)
        if request.method == "DELETE":
            return httpx.Response(200 if self.users.pop(uid, None) else 404, json={"deleted": True})
        return httpx.Response(405)


def bearer(clerk_id, **over):
    return {"Authorization": f"Bearer {token(sub=clerk_id, **over)}"}


def _user(**where):
    with SessionLocal() as db:
        return db.scalar(select(User).filter_by(**where))


def test_first_request_provisions_a_user_once(client, fake_clerk):
    fake_clerk.add("user_new", "Priya.Sharma@Example.com", first_name="Priya")
    r = client.get("/api/auth/me", headers=bearer("user_new"))
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "priya.sharma@example.com" and r.json()["display_name"] == "Priya"
    u = _user(external_id="user_new")
    assert u.auth_provider == "clerk" and u.password_hash is None and u.id == r.json()["id"]
    assert client.get("/api/auth/me", headers=bearer("user_new")).status_code == 200
    assert fake_clerk.calls == ["GET /v1/users/user_new"], "Backend API is called once, on first sight"


def test_unverified_email_gets_no_account(client, fake_clerk):
    fake_clerk.add("user_unv", "new@example.com", verified=False)
    r = client.get("/api/auth/me", headers=bearer("user_unv"))
    assert r.status_code == 403 and "Verify your email" in r.text
    assert _user(external_id="user_unv") is None


def test_clerk_outage_is_503_and_creates_nothing(client, fake_clerk):
    fake_clerk.add("user_down", "down@example.com")
    fake_clerk.down = True
    assert client.get("/api/auth/me", headers=bearer("user_down")).status_code == 503
    assert _user(external_id="user_down") is None


@pytest.mark.parametrize("over", [{"azp": "https://evil.example"}, {"exp": int(time.time()) - 60}, {"iss": "https://x.dev"}])
def test_bad_tokens_are_401(client, fake_clerk, over):
    fake_clerk.add("user_x", "x@example.com")
    assert client.get("/api/auth/me", headers=bearer("user_x", **over)).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    assert fake_clerk.calls == []


def _local_account(email):
    with SessionLocal() as db:
        u = User(email=email, password_hash=hash_password("correct-horse-1"), display_name="")
        db.add(u)
        db.commit()
        return u.id


def test_verified_email_links_existing_local_account(client, fake_clerk):
    local_id = _local_account("owner@example.com")
    fake_clerk.add("user_link", "OWNER@example.com", first_name="Sam")
    r = client.get("/api/auth/me", headers=bearer("user_link"))
    assert r.status_code == 200 and r.json()["id"] == local_id, "same account, same data"
    u = _user(id=local_id)
    assert u.external_id == "user_link" and u.password_hash is None and u.display_name == "Sam"


def test_unverified_email_cannot_take_over_a_local_account(client, fake_clerk):
    local_id = _local_account("victim@example.com")
    fake_clerk.add("user_attacker", "victim@example.com", verified=False)
    assert client.get("/api/auth/me", headers=bearer("user_attacker")).status_code == 403
    assert _user(id=local_id).external_id is None


def test_email_already_linked_to_another_clerk_user_is_409(client, fake_clerk):
    fake_clerk.add("user_first", "same@example.com")
    assert client.get("/api/auth/me", headers=bearer("user_first")).status_code == 200
    fake_clerk.add("user_second", "same@example.com")
    assert client.get("/api/auth/me", headers=bearer("user_second")).status_code == 409


def test_local_password_endpoints_are_off(client, fake_clerk):
    assert client.post("/api/auth/signup", json={"email": "a@example.com", "password": "correct-horse-1"}).status_code == 404
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "correct-horse-1"}).status_code == 404


def test_users_stay_isolated(client, fake_clerk, sample_pdf):
    fake_clerk.add("user_a", "a@example.com")
    fake_clerk.add("user_b", "b@example.com")
    doc = client.post("/api/documents?rights_confirmed=true", headers=bearer("user_a"),
                      files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()
    assert client.get(f"/api/documents/{doc['id']}", headers=bearer("user_b")).status_code == 404
    assert client.get("/api/documents", headers=bearer("user_b")).json() == []
    assert client.get(f"/api/documents/{doc['id']}", headers=bearer("user_a")).status_code == 200


def test_lookup_transaction_is_closed_so_rls_scope_applies(client, fake_clerk):
    """On Postgres, RLS is scoped when a transaction begins; the user lookup's must not be reused."""
    fake_clerk.add("user_tx", "tx@example.com")
    for _ in range(2):  # first call provisions, second finds the existing row
        db = SessionLocal()
        try:
            u = deps._clerk_user(token(sub="user_tx"), db)
            assert db.info["user_id"] == u.id and not db.in_transaction()
            assert u.email == "tx@example.com"  # still loaded: no expiry after closing the transaction
        finally:
            db.close()


def test_local_login_rejects_accounts_without_a_password(client):
    """password_hash is None once linked to Clerk: local login must 401, not crash."""
    with SessionLocal() as db:
        db.add(User(email="linked@example.com", password_hash=None, auth_provider="clerk", external_id="user_l"))
        db.commit()
    r = client.post("/api/auth/login", json={"email": "linked@example.com", "password": "correct-horse-1"})
    assert r.status_code == 401


# ---------------------------------------------------------------- claiming a signed-out report

def _report_token(client):
    from app.services import public_report
    from tests.test_interview_samples import SAMPLE_JD, SAMPLE_RESUME

    public_report.ip_limiter.reset()
    r = client.post("/api/public/gap-report", json={"resume_text": SAMPLE_RESUME, "job_text": SAMPLE_JD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_clerk_user_claims_a_signed_out_report_once(client, fake_clerk):
    fake_clerk.add("user_claim", "claim@example.com")
    report = _report_token(client)
    assert client.post("/api/public/claim", json={"report_token": report}).status_code == 401
    r = client.post("/api/public/claim", headers=bearer("user_claim"), json={"report_token": report})
    assert r.status_code == 200, r.text
    prep = client.get(f"/api/interview/preps/{r.json()['prep_id']}", headers=bearer("user_claim")).json()
    assert prep["skills"], "the report's skills became the prep's skill matrix"
    again = client.post("/api/public/claim", headers=bearer("user_claim"), json={"report_token": report})
    assert again.status_code == 404 and "expired" in again.text


def test_claim_also_works_with_local_auth(client):
    report = _report_token(client)
    tok = client.post("/api/auth/signup", json={"email": "local-claim@example.com", "password": "correct-horse-1"}).json()["token"]
    r = client.post("/api/public/claim", headers={"Authorization": f"Bearer {tok}"}, json={"report_token": report})
    assert r.status_code == 200 and r.json()["prep_id"]
