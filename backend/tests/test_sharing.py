"""Shareable prep plans: what a link shows and hides, expiry, revocation, hashing, isolation."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

tmp = tempfile.mkdtemp()
os.environ.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{tmp}/t.db", "STORAGE_DIR": tmp, "AI_PROVIDER": "mock"})

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models_share import PlanShare  # noqa: E402
from app.services import public_report  # noqa: E402
from tests.test_interview_samples import SAMPLE_JD, SAMPLE_RESUME  # noqa: E402

IV = "/api/interview"


def _prep(client, email="share@example.com", name="Priya"):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1", "display_name": name})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    resume = client.post(f"{IV}/resumes", headers=h, json={"text": SAMPLE_RESUME}).json()
    job = client.post(f"{IV}/jobs", headers=h, json={"text": SAMPLE_JD}).json()
    prep = client.post(f"{IV}/preps", headers=h, json={"resume_id": resume["id"], "job_id": job["id"],
                                                     "interview_date": "2026-12-01"}).json()
    return h, prep


def test_a_link_shows_the_plan_and_nothing_personal(client):
    public_report.share_view_limiter.reset()
    h, prep = _prep(client)
    r = client.post(f"{IV}/preps/{prep['id']}/shares", headers=h)
    assert r.status_code == 201
    url = r.json()["url"]
    token = url.rsplit("/share/", 1)[1]
    view = client.get(f"/api/public/shared-plans/{token}").json()
    assert view["role_title"].startswith("Analytics Manager") and view["interview_date"] == "2026-12-01"
    assert view["plan"] and view["skills"] and all(set(s) == {"name", "priority", "status"} for s in view["skills"])
    dump = str(view)
    for private in ("Priya", "share@example.com", "Northwind", "forecast accuracy by 8%", "+44"):
        assert private not in dump, private
    with SessionLocal() as db:
        row = db.scalar(select(PlanShare))
        assert token not in str(row.__dict__) and len(row.token_hash) == 64 and row.views == 1
    listed = client.get(f"{IV}/preps/{prep['id']}/shares", headers=h).json()
    assert len(listed) == 1 and listed[0]["url"] is None and listed[0]["views"] == 1


def test_revoked_expired_and_unknown_links_are_404(client):
    public_report.share_view_limiter.reset()
    h, prep = _prep(client, "s2@example.com")
    a = client.post(f"{IV}/preps/{prep['id']}/shares", headers=h).json()
    b = client.post(f"{IV}/preps/{prep['id']}/shares", headers=h).json()
    ta, tb = a["url"].rsplit("/", 1)[1], b["url"].rsplit("/", 1)[1]
    assert client.delete(f"{IV}/preps/{prep['id']}/shares/{a['id']}", headers=h).status_code == 204
    assert client.get(f"/api/public/shared-plans/{ta}").status_code == 404
    with SessionLocal() as db:
        db.get(PlanShare, b["id"]).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.get(f"/api/public/shared-plans/{tb}").status_code == 404
    assert client.get("/api/public/shared-plans/not-a-real-token").status_code == 404
    assert client.get(f"{IV}/preps/{prep['id']}/shares", headers=h).json() == []


def test_only_the_owner_manages_links(client):
    h, prep = _prep(client, "s3@example.com")
    r = client.post("/api/auth/signup", json={"email": "other@example.com", "password": "correct-horse-1"})
    other = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.post(f"{IV}/preps/{prep['id']}/shares", headers=other).status_code == 404
    share = client.post(f"{IV}/preps/{prep['id']}/shares", headers=h).json()
    assert client.delete(f"{IV}/preps/{prep['id']}/shares/{share['id']}", headers=other).status_code == 404


def test_public_reads_are_rate_limited(client):
    public_report.share_view_limiter.reset()
    codes = [client.get("/api/public/shared-plans/x").status_code for _ in range(61)]
    assert codes[:60] == [404] * 60 and codes[60] == 429
