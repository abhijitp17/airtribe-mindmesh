"""Today stops asking "What are you preparing for?" once the user has shown it (Wave 4 fix)."""
import time

from app.services import public_report
from tests.test_interview_samples import SAMPLE_JD, SAMPLE_RESUME


def _signup(client, email, **extra):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1", **extra})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _prefs(client, h):
    return client.get("/api/me/prefs", headers=h).json()


def test_new_user_is_asked(client):
    h = _signup(client, "fresh@example.com")
    p = _prefs(client, h)
    assert p["onboarded"] is False and p["preparing_for"] is None


def test_uploading_material_counts_as_onboarded(client, sample_pdf):
    h = _signup(client, "uploader@example.com")
    doc = client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()
    for _ in range(50):
        if client.get(f"/api/documents/{doc['id']}", headers=h).json()["status"] == "ready":
            break
        time.sleep(0.05)
    p = _prefs(client, h)
    assert p["onboarded"] is True and p["preparing_for"] == "learn"


def test_saved_report_means_preparing_for_an_interview(client):
    public_report.ip_limiter.reset()
    rep = client.post("/api/public/gap-report", json={"resume_text": SAMPLE_RESUME, "job_text": SAMPLE_JD}).json()
    h = _signup(client, "candidate@example.com", report_token=rep["token"])
    p = _prefs(client, h)
    assert p["onboarded"] is True and p["preparing_for"] == "interview"
    assert client.get("/api/today/preview", headers=h).status_code == 200


def test_an_explicit_choice_is_kept(client, sample_pdf):
    h = _signup(client, "chooser@example.com")
    assert client.patch("/api/me/prefs", headers=h, json={"preparing_for": "exam"}).status_code == 200
    client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": ("a.pdf", sample_pdf, "application/pdf")})
    assert _prefs(client, h)["preparing_for"] == "exam"
