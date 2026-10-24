"""API tests for interview prep (CONTRACTS.md §3): full flow, uploads, overrides, isolation.

Requires the backend dependencies (pip install -r requirements-dev.txt).
"""
import io
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_interview.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests.conftest import make_pdf  # noqa: E402
from tests.test_interview_samples import SAMPLE_JD, SAMPLE_RESUME  # noqa: E402

BASE = "/api/interview"
STAR = (
    "When I was at Northwind our forecasts missed demand peaks. My goal was to cut forecast error. I built a "
    "gradient boosting model and first compared it with the moving-average baseline on a six month holdout. "
    "As a result accuracy improved 8%. In hindsight I would involve store managers earlier; the trade-off was interpretability."
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _prep(client, h, **extra):
    resume = client.post(f"{BASE}/resumes", headers=h, json={"text": SAMPLE_RESUME})
    assert resume.status_code == 201, resume.text
    job = client.post(f"{BASE}/jobs", headers=h, json={"text": SAMPLE_JD})
    assert job.status_code == 201, job.text
    prep = client.post(f"{BASE}/preps", headers=h, json={"resume_id": resume.json()["id"], "job_id": job.json()["id"], **extra})
    assert prep.status_code == 201, prep.text
    return resume.json(), job.json(), prep.json()


def test_resume_text_and_file_uploads(client):
    h = _signup(client, "resume@example.com")
    r = client.post(f"{BASE}/resumes", headers=h, json={"text": SAMPLE_RESUME}).json()
    assert r["source_filename"] is None and r["user_confirmed"] is False
    assert r["parsed"]["roles"][0]["bullets"][0]["id"] == "r1b1"

    pdf = make_pdf([SAMPLE_RESUME.splitlines()])
    up = client.post(f"{BASE}/resumes", headers=h, files={"file": ("cv.pdf", pdf, "application/pdf")})
    assert up.status_code == 201, up.text
    assert up.json()["source_filename"] == "cv.pdf" and up.json()["parsed"]["roles"]

    import docx
    d = docx.Document()
    for line in SAMPLE_RESUME.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    up = client.post(f"{BASE}/resumes", headers=h, files={"file": ("cv.docx", buf.getvalue(), "application/octet-stream")})
    assert up.status_code == 201, up.text

    assert client.post(f"{BASE}/resumes", headers=h, files={"file": ("a.txt", b"hello")}).status_code == 415
    assert client.post(f"{BASE}/resumes", headers=h, json={"text": "too short"}).status_code == 422
    assert client.post(f"{BASE}/resumes", headers=h, json={"nope": 1}).status_code == 422
    assert len(client.get(f"{BASE}/resumes", headers=h).json()) == 3


def test_resume_and_job_edits_are_confirmed(client):
    h = _signup(client, "edit@example.com")
    r = client.post(f"{BASE}/resumes", headers=h, json={"text": SAMPLE_RESUME}).json()
    parsed = r["parsed"]
    parsed["roles"][0]["bullets"].append({"id": "", "text": "Ran weekly forecasting reviews with category leads"})
    out = client.put(f"{BASE}/resumes/{r['id']}", headers=h, json={"parsed": parsed}).json()
    assert out["user_confirmed"] is True
    ids = [b["id"] for b in out["parsed"]["roles"][0]["bullets"]]
    assert len(ids) == len(set(ids)) and all(ids)

    job = client.post(f"{BASE}/jobs", headers=h, json={"text": SAMPLE_JD}).json()
    jp = job["parsed"]
    jp["competencies"] = jp["competencies"][:3]
    edited = client.put(f"{BASE}/jobs/{job['id']}", headers=h, json={"parsed": jp}).json()
    assert edited["user_confirmed"] is True and len(edited["parsed"]["competencies"]) == 3
    assert client.get(f"{BASE}/jobs/{job['id']}", headers=h).json()["parsed"]["role_title"] == "Analytics Manager"


def test_prep_matrix_plan_readiness_and_overrides(client):
    h = _signup(client, "prep@example.com")
    _, job, prep = _prep(client, h, interview_date="2026-12-01")
    assert prep["role_title"] == "Analytics Manager" and prep["interview_date"] == "2026-12-01"
    assert len(prep["skills"]) == len(job["parsed"]["competencies"])
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    assert [order[s["priority"]] for s in prep["skills"]] == sorted(order[s["priority"]] for s in prep["skills"])
    s0 = prep["skills"][0]
    assert set(s0["priority_factors"]) == {"importance", "gap_severity", "evidence_confidence", "urgency", "feasibility"}
    assert all("strength" not in e for s in prep["skills"] for e in s["resume_evidence"])
    assert prep["plan"][-1]["activity"] == "mock_interview"
    assert {d["dimension"] for d in prep["readiness"]} == {"role_knowledge", "applied_problem_solving", "resume_evidence", "behavioral_examples", "communication"}

    low = next(s for s in prep["skills"] if s["priority"] == "low")
    r = client.patch(f"{BASE}/preps/{prep['id']}/skills/{low['id']}", headers=h, json={"priority": "critical", "note": "Team uses it daily"})
    assert r.status_code == 200, r.text
    assert r.json()["user_override"] == {"priority": "critical", "note": "Team uses it daily"}
    after = client.get(f"{BASE}/preps/{prep['id']}", headers=h).json()
    pos = [s["id"] for s in after["skills"]].index(low["id"])  # same id, moved into the critical group
    assert all((s["user_override"] or {}).get("priority", s["priority"]) == "critical" for s in after["skills"][: pos + 1])
    assert after["skills"][pos]["priority"] == "low"  # computed value stays visible
    cleared = client.patch(f"{BASE}/preps/{prep['id']}/skills/{low['id']}", headers=h, json={"priority": None, "note": None}).json()
    assert cleared["user_override"] is None

    patched = client.patch(f"{BASE}/preps/{prep['id']}", headers=h, json={"interview_date": None}).json()
    assert patched["interview_date"] is None
    again = client.post(f"{BASE}/preps/{prep['id']}/recompute", headers=h).json()
    assert {s["id"] for s in again["skills"]} == {s["id"] for s in prep["skills"]}

    summary = client.get(f"{BASE}/preps", headers=h).json()
    assert summary[0]["id"] == prep["id"] and summary[0]["sessions"] == 0

    dd = client.get(f"{BASE}/preps/{prep['id']}/deep-dive", headers=h).json()
    assert dd and dd[0]["bullet_id"] == "r1b1" and any("baseline" in q for q in dd[0]["questions"])


def test_mock_interview_session_flow(client):
    h = _signup(client, "session@example.com")
    _, _, prep = _prep(client, h)
    s = client.post(f"{BASE}/preps/{prep['id']}/sessions", headers=h, json={"focus": "behavioral", "target_questions": 3})
    assert s.status_code == 201, s.text
    session = s.json()
    assert session["status"] == "active" and len(session["turns"]) == 1 and session["turns"][0]["answer"] is None
    assert client.post(f"{BASE}/preps/{prep['id']}/sessions", headers=h, json={"target_questions": 20}).status_code == 422

    for _ in range(10):
        r = client.post(f"{BASE}/sessions/{session['id']}/answer", headers=h, json={"answer": STAR})
        assert r.status_code == 200, r.text
        session = r.json()
        if session["status"] == "completed":
            break
    assert session["status"] == "completed" and session["summary"]["overall"]
    graded = session["turns"][0]["evaluation"]
    assert graded["star"] is not None and 0 <= graded["score"] <= 1
    assert client.post(f"{BASE}/sessions/{session['id']}/answer", headers=h, json={"answer": STAR}).status_code == 409

    listed = client.get(f"{BASE}/preps/{prep['id']}/sessions", headers=h).json()
    assert listed[0]["questions"] == 3 and listed[0]["avg_score"] is not None

    second = client.post(f"{BASE}/preps/{prep['id']}/sessions", headers=h).json()
    ended = client.post(f"{BASE}/sessions/{second['id']}/end", headers=h).json()
    assert ended["status"] == "completed" and ended["ended_at"] and ended["summary"]["by_competency"] == []

    readiness = client.get(f"{BASE}/preps/{prep['id']}", headers=h).json()["readiness"]
    assert next(d for d in readiness if d["dimension"] == "communication")["evidence_count"] > 0


def test_cross_user_isolation(client):
    owner = _signup(client, "owner-iv@example.com")
    intruder = _signup(client, "intruder-iv@example.com")
    resume, job, prep = _prep(client, owner)
    session = client.post(f"{BASE}/preps/{prep['id']}/sessions", headers=owner, json={}).json()
    skill_id = prep["skills"][0]["id"]

    for method, url, kw in [
        ("get", f"{BASE}/resumes/{resume['id']}", {}),
        ("put", f"{BASE}/resumes/{resume['id']}", {"json": {"parsed": resume["parsed"]}}),
        ("delete", f"{BASE}/resumes/{resume['id']}", {}),
        ("get", f"{BASE}/jobs/{job['id']}", {}),
        ("put", f"{BASE}/jobs/{job['id']}", {"json": {"parsed": job["parsed"]}}),
        ("delete", f"{BASE}/jobs/{job['id']}", {}),
        ("post", f"{BASE}/preps", {"json": {"resume_id": resume["id"], "job_id": job["id"]}}),
        ("get", f"{BASE}/preps/{prep['id']}", {}),
        ("post", f"{BASE}/preps/{prep['id']}/recompute", {}),
        ("patch", f"{BASE}/preps/{prep['id']}", {"json": {"interview_date": None}}),
        ("patch", f"{BASE}/preps/{prep['id']}/skills/{skill_id}", {"json": {"priority": "low"}}),
        ("get", f"{BASE}/preps/{prep['id']}/deep-dive", {}),
        ("post", f"{BASE}/preps/{prep['id']}/sessions", {"json": {}}),
        ("get", f"{BASE}/preps/{prep['id']}/sessions", {}),
        ("get", f"{BASE}/sessions/{session['id']}", {}),
        ("post", f"{BASE}/sessions/{session['id']}/answer", {"json": {"answer": STAR}}),
        ("post", f"{BASE}/sessions/{session['id']}/end", {}),
        ("delete", f"{BASE}/preps/{prep['id']}", {}),
    ]:
        r = getattr(client, method)(url, headers=intruder, **kw)
        assert r.status_code == 404, (method, url, r.status_code)
    assert client.get(f"{BASE}/resumes", headers=intruder).json() == []
    assert client.get(f"{BASE}/preps", headers=intruder).json() == []
    assert client.get(f"{BASE}/preps/{prep['id']}", headers=owner).status_code == 200
    assert client.get(f"{BASE}/resumes").status_code == 401


def test_deletes_cascade(client):
    h = _signup(client, "delete-iv@example.com")
    resume, job, prep = _prep(client, h)
    assert client.delete(f"{BASE}/preps/{prep['id']}", headers=h).status_code == 204
    assert client.get(f"{BASE}/preps/{prep['id']}", headers=h).status_code == 404
    _, _, prep2 = _prep(client, h)
    assert client.delete(f"{BASE}/jobs/{prep2['job_id']}", headers=h).status_code == 204
    assert client.get(f"{BASE}/preps/{prep2['id']}", headers=h).status_code == 404
    assert client.delete(f"{BASE}/resumes/{resume['id']}", headers=h).status_code == 204
    assert client.delete(f"{BASE}/jobs/{job['id']}", headers=h).status_code == 204
