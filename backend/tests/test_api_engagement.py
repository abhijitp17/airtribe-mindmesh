"""API tests for engagement and the public report (CONTRACTS §7).

Requires the backend dependencies (pip install -r requirements-dev.txt).
"""
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_engagement.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas import SignupIn  # noqa: E402
from app.services import public_report  # noqa: E402
from tests.test_interview_samples import SAMPLE_JD, SAMPLE_RESUME  # noqa: E402

IV = "/api/interview"


def _today():
    return datetime.now(timezone.utc).date()
STEP_KEYS = {"id", "kind", "title", "detail", "minutes", "concept", "target", "status"}


@pytest.fixture
def client():
    public_report.ip_limiter.reset()
    public_report.cache.clear()
    with TestClient(app) as c:
        yield c


def _signup(client, email, **extra):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1", **extra})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _upload(client, h, pdf):
    r = client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": ("fp.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    for _ in range(50):
        d = client.get(f"/api/documents/{doc_id}", headers=h).json()
        if d["status"] not in ("uploaded", "processing"):
            return d
        time.sleep(0.05)
    raise AssertionError("processing did not finish")


def _prep(client, h, **extra):
    resume = client.post(f"{IV}/resumes", headers=h, json={"text": SAMPLE_RESUME}).json()
    job = client.post(f"{IV}/jobs", headers=h, json={"text": SAMPLE_JD}).json()
    r = client.post(f"{IV}/preps", headers=h, json={"resume_id": resume["id"], "job_id": job["id"], **extra})
    assert r.status_code == 201, r.text
    return r.json()


# ---------- prefs ----------

def test_prefs_defaults_and_patch(client):
    h = _signup(client, "prefs@example.com")
    p = client.get("/api/me/prefs", headers=h).json()
    assert p == {"preparing_for": None, "weekly_target": 3, "default_minutes": 15, "reminders": False,
                 "quiet_start": "21:00", "quiet_end": "08:00", "reduce_transparency": False, "onboarded": False}
    p = client.patch("/api/me/prefs", headers=h, json={"preparing_for": "interview", "weekly_target": 5,
                                                         "default_minutes": 5, "onboarded": True}).json()
    assert p["preparing_for"] == "interview" and p["weekly_target"] == 5 and p["default_minutes"] == 5 and p["onboarded"]
    for bad in ({"weekly_target": 0}, {"weekly_target": 8}, {"default_minutes": 10}, {"quiet_start": "25:00"},
                {"quiet_end": "9:00"}, {"onboarded": False}):
        assert client.patch("/api/me/prefs", headers=h, json=bad).status_code == 422, bad
    assert client.get("/api/me/prefs").status_code == 401


# ---------- today, week, sessions ----------

def test_empty_today(client):
    h = _signup(client, "empty@example.com", display_name="Sam Lee")
    t = client.get("/api/today/preview", headers=h).json()
    assert t["greeting_name"] == "Sam" and t["empty_reason"] == "no_material" and t["library_count"] == 0
    assert t["suggestions"] == {"5": [], "15": [], "30": []}
    assert t["countdown"] is None and t["debrief_due"] is None and t["last_win"] is None
    assert len(t["week"]["days"]) == 7 and t["week"]["done"] == 0
    assert client.post("/api/sessions/study", headers=h, json={"minutes": 15}).status_code == 422


def test_session_lifecycle(client, sample_pdf):
    h = _signup(client, "learner@example.com")
    doc = _upload(client, h, sample_pdf)
    t = client.get("/api/today/preview", headers=h).json()
    assert t["empty_reason"] == "no_goal" and t["library_count"] == 1
    for k in ("5", "15", "30"):
        steps = t["suggestions"][k]
        assert steps and sum(s["minutes"] for s in steps) <= int(k)
        assert all(set(s) == STEP_KEYS for s in steps)
    assert len(t["suggestions"]["5"]) == 1
    assert t["suggestions"]["5"][0]["title"].startswith("Take a 5-question quiz on")

    assert client.post("/api/sessions/study", headers=h, json={"minutes": 10}).status_code == 422
    s = client.post("/api/sessions/study", headers=h, json={"minutes": 15})
    assert s.status_code == 201, s.text
    s = s.json()
    assert s["status"] == "active" and s["wins"] == [] and s["completed_at"] is None and s["minutes"] == 15
    step = s["steps"][0]
    assert step["target"]["type"] == "quiz" and step["target"]["document_ids"] == [doc["id"]]

    quiz = client.post("/api/quizzes", headers=h, json={"document_ids": [doc["id"]], "count": 4}).json()
    for q in quiz["questions"]:
        body = {"selected_index": 0} if q["qtype"] == "mcq" else {"answer_text": "WIP equals throughput times cycle time."}
        assert client.post(f"/api/questions/{q['id']}/attempts", headers=h, json=body).status_code == 201

    r = client.patch(f"/api/sessions/study/{s['id']}/steps/{step['id']}", headers=h, json={"status": "done", "quiz_id": quiz["id"]})
    assert r.status_code == 200, r.text
    got = r.json()["steps"][0]
    assert got["status"] == "done" and got["target"]["quiz_id"] == quiz["id"]
    assert client.patch(f"/api/sessions/study/{s['id']}/steps/nope", headers=h, json={"status": "done"}).status_code == 404
    assert client.patch(f"/api/sessions/study/{s['id']}/steps/{step['id']}", headers=h, json={"status": "pending"}).status_code == 422

    done = client.post(f"/api/sessions/study/{s['id']}/complete", headers=h).json()
    assert done["status"] == "completed" and done["completed_at"]
    kinds = [w["kind"] for w in done["wins"]]
    assert "first_answer" in kinds
    assert all(set(w) == {"kind", "title", "detail"} for w in done["wins"])
    assert client.post(f"/api/sessions/study/{s['id']}/complete", headers=h).json() == done  # idempotent
    assert client.patch(f"/api/sessions/study/{s['id']}/steps/{step['id']}", headers=h, json={"status": "skipped"}).status_code == 409

    wk = client.get("/api/week", headers=h).json()
    assert wk["done"] >= 1 and any(d["is_today"] and d["practised"] for d in wk["days"])
    t = client.get("/api/today/preview", headers=h).json()
    assert t["last_win"] == done["wins"][0]
    assert client.get(f"/api/sessions/study/{s['id']}", headers=h).json()["id"] == s["id"]


def test_countdown_and_prep_steps(client):
    h = _signup(client, "prep@example.com")
    when = (_today() + timedelta(days=9)).isoformat()
    prep = _prep(client, h, interview_date=when)
    t = client.get("/api/today/preview", headers=h).json()
    assert t["countdown"]["prep_id"] == prep["id"] and t["countdown"]["days_left"] == 9
    assert t["countdown"]["interview_date"] == when and t["countdown"]["company"] == "Fabrikam Foods"
    steps = t["suggestions"]["15"]
    assert steps and steps[0]["kind"] in ("story", "mock_question", "learn")
    assert "Fabrikam Foods" in steps[0]["detail"]


# ---------- debrief ----------

def test_debrief_follow_ups(client):
    h = _signup(client, "debrief@example.com")
    prep = _prep(client, h)
    past = (_today() - timedelta(days=2)).isoformat()
    assert client.patch(f"{IV}/preps/{prep['id']}", headers=h, json={"interview_date": past}).status_code == 200
    t = client.get("/api/today/preview", headers=h).json()
    assert t["debrief_due"] == {"prep_id": prep["id"], "role_title": prep["role_title"], "company": prep["company"], "interview_date": past}

    bad = client.post(f"{IV}/preps/{prep['id']}/debrief", headers=h, json={"outcome": "great", "next_step": None})
    assert bad.status_code == 422
    r = client.post(f"{IV}/preps/{prep['id']}/debrief", headers=h, json={"outcome": "next_round", "next_step": "next_round", "note": "Went OK"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert set(d) == {"id", "prep_id", "outcome", "note", "next_step", "created_at", "follow_up"}
    assert d["follow_up"]["type"] == "prep" and d["follow_up"]["id"] != prep["id"]
    copy = client.get(f"{IV}/preps/{d['follow_up']['id']}", headers=h).json()
    assert copy["interview_date"] is None and len(copy["skills"]) == len(prep["skills"])
    assert client.get("/api/today/preview", headers=h).json()["debrief_due"] is None
    assert client.post(f"{IV}/preps/{prep['id']}/debrief", headers=h, json={"outcome": "offer"}).status_code == 409

    g = client.post(f"{IV}/preps/{copy['id']}/debrief", headers=h, json={"outcome": "rejected", "next_step": "learning_goal"})
    assert g.status_code == 201, g.text
    fu = g.json()["follow_up"]
    assert fu["type"] == "goal"
    goal = client.get(f"/api/goals/{fu['id']}", headers=h).json()
    assert goal["goal_type"] == "learn" and goal["items"]

    other = _prep(client, h)
    n = client.post(f"{IV}/preps/{other['id']}/debrief", headers=h, json={"outcome": "prefer_not", "next_step": "none"}).json()
    assert n["follow_up"] is None and n["next_step"] == "none"


# ---------- isolation ----------

def test_cross_user_404(client, sample_pdf):
    a = _signup(client, "owner@example.com")
    b = _signup(client, "intruder@example.com")
    _upload(client, a, sample_pdf)
    s = client.post("/api/sessions/study", headers=a, json={"minutes": 5}).json()
    prep = _prep(client, a)
    assert client.get(f"/api/sessions/study/{s['id']}", headers=b).status_code == 404
    assert client.patch(f"/api/sessions/study/{s['id']}/steps/{s['steps'][0]['id']}", headers=b, json={"status": "done"}).status_code == 404
    assert client.post(f"/api/sessions/study/{s['id']}/complete", headers=b).status_code == 404
    assert client.post(f"{IV}/preps/{prep['id']}/debrief", headers=b, json={"outcome": "offer"}).status_code == 404
    assert client.get("/api/today/preview", headers=b).json()["countdown"] is None


# ---------- public report ----------

def test_public_gap_report_and_rate_limit(client):
    assert client.post("/api/public/gap-report", json={"resume_text": "short", "job_text": SAMPLE_JD}).status_code == 422
    r = client.post("/api/public/gap-report", json={"resume_text": SAMPLE_RESUME, "job_text": SAMPLE_JD})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert set(rep) == {"token", "role_title", "company", "skills", "hidden_count", "warnings", "expires_at"}
    assert 0 < len(rep["skills"]) <= 5 and rep["role_title"]
    for s in rep["skills"]:
        assert set(s) == {"name", "importance", "gap_type", "priority", "assessed_level", "evidence_quote", "jd_quote", "why", "next_step"}
    for _ in range(4):
        assert client.post("/api/public/gap-report", json={"resume_text": SAMPLE_RESUME, "job_text": SAMPLE_JD}).status_code == 200
    limited = client.post("/api/public/gap-report", json={"resume_text": SAMPLE_RESUME, "job_text": SAMPLE_JD})
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0


def test_claim_report_on_signup(client):
    if "report_token" not in SignupIn.model_fields:
        pytest.skip("signup claim not wired yet (integrator patch to schemas.SignupIn + routers/auth.py)")
    rep = client.post("/api/public/gap-report", json={"resume_text": SAMPLE_RESUME, "job_text": SAMPLE_JD}).json()
    h = _signup(client, "claimer@example.com", report_token=rep["token"])
    preps = client.get(f"{IV}/preps", headers=h).json()
    assert len(preps) == 1 and preps[0]["role_title"] == rep["role_title"]
    full = client.get(f"{IV}/preps/{preps[0]['id']}", headers=h).json()
    assert len(full["skills"]) == len(rep["skills"]) + rep["hidden_count"]
    # single use
    h2 = _signup(client, "claimer2@example.com", report_token=rep["token"])
    assert client.get(f"{IV}/preps", headers=h2).json() == []
