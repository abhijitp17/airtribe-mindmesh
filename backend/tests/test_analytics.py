"""Product events, activation, the onboarding experiment and its report."""
import os
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_analytics.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.models_analytics import ProductEvent  # noqa: E402
from app.services import analytics as an  # noqa: E402
from app.services import public_report  # noqa: E402
from tests.test_interview_samples import SAMPLE_JD, SAMPLE_RESUME  # noqa: E402


def _signup(client, email, **extra):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1", **extra})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]["id"]


def _events(uid):
    with SessionLocal() as db:
        return [(e.name, e.props) for e in db.scalars(select(ProductEvent).where(ProductEvent.owner_id == uid)
                                                    .order_by(ProductEvent.created_at))]


def _upload(client, h, pdf):
    r = client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": ("a.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------- pure

def test_props_are_allowlisted_and_content_free():
    assert an.clean_props("tutor_answer", {"status": "verified", "question": "What is Little's Law?"}) == {"status": "verified"}
    assert an.clean_props("tutor_answer", {"status": "Verified answer with spaces"}) == {}
    assert an.clean_props("quiz_created", {"count": 5}) == {"count": 5}
    assert an.clean_props("quiz_created", {"count": -1}) == {}
    assert an.clean_props("session_completed", {"minutes": 15, "note": "x"}) == {"minutes": 15}
    assert an.clean_props("nonexistent", {"a": 1}) == {}


def test_variants_are_stable_balanced_and_overridable():
    ids = [f"user{i:05d}" for i in range(4000)]
    arms = Counter(an.variant("onboarding", u, "on") for u in ids)
    assert set(arms) == {"goal_first", "upload_first"} and abs(arms["goal_first"] - 2000) < 150
    assert all(an.variant("onboarding", u, "on") == an.variant("onboarding", u, "on") for u in ids[:50])
    assert an.variant("onboarding", ids[0], "off") == "goal_first"
    assert an.variant("onboarding", ids[0], "upload_first") == "upload_first"


def test_two_proportion_p():
    assert an.two_proportion_p(50, 100, 50, 100) == pytest.approx(1.0)
    assert an.two_proportion_p(60, 100, 40, 100) < 0.01
    assert an.two_proportion_p(0, 0, 1, 10) is None and an.two_proportion_p(0, 10, 0, 10) is None


# ---------------------------------------------------------------- server-side events and activation

def test_learning_path_activates_once(client, sample_pdf):
    h, uid = _signup(client, "learn@example.com")
    doc = _upload(client, h, sample_pdf)
    assert client.post("/api/tutor/ask", headers=h, json={"question": "What is Little's Law?", "document_ids": [doc]}).json()["status"] == "verified"
    assert "activated" not in [n for n, _ in _events(uid)], "an answer alone isn't activation"
    quiz = client.post("/api/quizzes", headers=h, json={"document_ids": [doc], "count": 3}).json()
    for q in quiz["questions"][:2]:
        body = {"selected_index": 0} if q["qtype"] == "mcq" else {"answer_text": "x"}
        assert client.post(f"/api/questions/{q['id']}/attempts", headers=h, json=body).status_code == 201

    names = [n for n, _ in _events(uid)]
    assert names[:2] == ["signed_up", "document_uploaded"]
    assert {"tutor_answer", "quiz_created", "question_answered"} <= set(names)
    activated = [p for n, p in _events(uid) if n == "activated"]
    assert len(activated) == 1 and activated[0]["path"] == "learning" and 0 <= activated[0]["seconds"] < 120


def test_gap_report_claim_activates(client):
    public_report.ip_limiter.reset()
    report = client.post("/api/public/gap-report", json={"resume_text": SAMPLE_RESUME, "job_text": SAMPLE_JD}).json()
    h, uid = _signup(client, "claim@example.com", report_token=report["token"])
    names = [n for n, _ in _events(uid)]
    assert ("gap_report_ready", {"source": "claim"}) in _events(uid)
    assert names.count("activated") == 1 and [p["path"] for n, p in _events(uid) if n == "activated"] == ["gap_report"]


def test_events_never_store_content(client, sample_pdf):
    h, uid = _signup(client, "content@example.com")
    doc = _upload(client, h, sample_pdf)
    client.post("/api/tutor/ask", headers=h, json={"question": "Secret question about variability?", "document_ids": [doc]})
    dump = str(_events(uid))
    assert "Secret" not in dump and "variability" not in dump.lower() and "a.pdf" not in dump


def test_analytics_failure_never_breaks_the_request(client, sample_pdf, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("analytics down")
    monkeypatch.setattr(an, "check_activation", boom)
    h, _ = _signup(client, "robust@example.com")
    assert client.post("/api/documents?rights_confirmed=true", headers=h,
                       files={"file": ("a.pdf", sample_pdf, "application/pdf")}).status_code == 201


# ---------------------------------------------------------------- experiment endpoints

def test_experiment_variant_and_exposure(client):
    h, uid = _signup(client, "exp@example.com")
    v = client.get("/api/me/experiments", headers=h).json()["onboarding"]
    assert v == an.variant("onboarding", uid)
    # The client can't pick its own arm: the server records the real one.
    other = "upload_first" if v == "goal_first" else "goal_first"
    r = client.post("/api/events", headers=h, json={"name": "onboarding_shown", "props": {"variant": other}})
    assert r.status_code == 204
    assert ("onboarding_shown", {"experiment": "onboarding", "variant": v}) in _events(uid)
    assert client.post("/api/events", headers=h, json={"name": "onboarding_choice", "props": {"variant": v, "choice": "upload"}}).status_code == 204
    assert client.post("/api/events", headers=h, json={"name": "activated", "props": {}}).status_code == 422
    assert client.post("/api/events", json={"name": "onboarding_shown"}).status_code == 401


def test_experiment_summary_counts_by_arm_and_window():
    now = datetime.now(timezone.utc) + timedelta(days=1)  # its own window: other tests' exposures are earlier
    with SessionLocal() as db:
        users = []
        for i in range(8):
            u = User(email=f"s{i}@example.com", password_hash="x", display_name="")
            db.add(u)
            users.append(u)
        db.flush()
        arms = ["goal_first"] * 4 + ["upload_first"] * 4
        secs = [60, 600, None, None, 100, 150, 90_000, None]  # activation seconds after sign-up
        for u, arm, s in zip(users, arms, secs):
            db.add(ProductEvent(owner_id=u.id, name="onboarding_shown", props={"experiment": "onboarding", "variant": arm},
                                created_at=now))
            db.add(ProductEvent(owner_id=u.id, name="onboarding_shown", props={"experiment": "onboarding", "variant": "goal_first"},
                                created_at=now + timedelta(minutes=5)))  # a later re-render doesn't move them
            if s is not None:
                db.add(ProductEvent(owner_id=u.id, name="activated", props={"path": "learning", "seconds": s}))
        db.commit()
        s = an.experiment_summary(db, "onboarding", since=now - timedelta(minutes=1))
    assert {k: v for k, v in s["arms"]["goal_first"].items() if k != "returned 7d"} == {"exposed": 4, "3 min": 1, "1 day": 2, "7 days": 2}
    assert {k: v for k, v in s["arms"]["upload_first"].items() if k != "returned 7d"} == {"exposed": 4, "3 min": 2, "1 day": 2, "7 days": 3}
    assert set(s["p_values"]) == {"3 min", "1 day", "7 days", "returned 7d"}


def test_retention_counts_a_return_on_a_later_day_within_a_week():
    from datetime import datetime, timedelta, timezone

    with SessionLocal() as db:
        base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
        users = []
        for i, later in enumerate([None, timedelta(hours=2), timedelta(days=2), timedelta(days=9)]):
            u = User(email=f"ret{i}@example.com", password_hash="x", display_name="", created_at=base)
            db.add(u)
            db.flush()
            users.append(u.id)
            if later is not None:
                db.add(ProductEvent(owner_id=u.id, name="document_uploaded", props={}, created_at=base + later))
        db.commit()
        assert an._returned_within(db, users) == {users[2]}


def test_report_tool_runs(capsys):
    from app.tools import experiment_report

    assert experiment_report.main([]) == 0
    out = capsys.readouterr().out
    assert "goal_first" in out and "upload_first" in out and "p-value" in out
