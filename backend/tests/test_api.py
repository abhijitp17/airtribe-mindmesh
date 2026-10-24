"""API tests: full learning loop and cross-user isolation (FR-015).

Requires the backend dependencies (pip install -r requirements-dev.txt).
"""
import os
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _upload(client, headers, pdf):
    r = client.post("/api/documents?rights_confirmed=true", headers=headers, files={"file": ("fp.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    for _ in range(50):
        d = client.get(f"/api/documents/{doc_id}", headers=headers).json()
        if d["status"] not in ("uploaded", "processing"):
            return d
        time.sleep(0.05)
    raise AssertionError("processing did not finish")


def test_full_learning_loop(client, sample_pdf):
    h = _signup(client, "alice@example.com")
    assert client.get("/api/progress", headers=h).json()["next_action"]["type"] == "upload"

    # rights confirmation and file type are enforced
    assert client.post("/api/documents", headers=h, files={"file": ("a.pdf", sample_pdf)}).status_code == 400
    assert client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": ("a.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")}).status_code == 415

    doc = _upload(client, h, sample_pdf)
    assert doc["status"] == "ready" and doc["page_count"] == 2
    # idempotent re-upload
    again = client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": ("fp.pdf", sample_pdf)}).json()
    assert again["id"] == doc["id"]

    chunks = client.get(f"/api/documents/{doc['id']}/chunks?page=2", headers=h).json()
    assert chunks and all(c["page_start"] <= 2 <= c["page_end"] for c in chunks)

    ans = client.post("/api/tutor/ask", headers=h, json={"question": "What is Little's Law?", "document_ids": [doc["id"]]}).json()
    assert ans["status"] == "verified"
    assert ans["citations"][0]["page_start"] == 1 and ans["citations"][0]["document_id"] == doc["id"]
    assert len(client.get("/api/tutor/history", headers=h, params={"document_ids": [doc["id"]]}).json()) == 2

    quiz = client.post("/api/quizzes", headers=h, json={"document_ids": [doc["id"]], "count": 4}).json()
    assert quiz["questions"]
    first = quiz["questions"][0]
    assert "answer_key" not in first and first["sources"][0]["document_id"] == doc["id"]

    for q in quiz["questions"]:
        body = {"selected_index": 0} if q["qtype"] == "mcq" else {"answer_text": "I don't know"}
        r = client.post(f"/api/questions/{q['id']}/attempts", headers=h, json=body)
        assert r.status_code == 201, r.text
        assert r.json()["verdict"] in ("correct", "partial", "incorrect")

    prog = client.get("/api/progress", headers=h).json()
    assert prog["totals"]["attempts"] == len(quiz["questions"])
    assert prog["concepts"]
    summary = client.get("/api/quizzes", headers=h).json()[0]
    assert summary["answered"] == len(quiz["questions"])

    assert client.post(f"/api/questions/{first['id']}/flag", headers=h, json={"reason": "ambiguous"}).status_code == 204


def test_cross_user_isolation(client, sample_pdf):
    owner = _signup(client, "owner@example.com")
    intruder = _signup(client, "intruder@example.com")
    doc = _upload(client, owner, sample_pdf)
    quiz = client.post("/api/quizzes", headers=owner, json={"document_ids": [doc["id"]], "count": 3}).json()
    qid = quiz["questions"][0]["id"]

    for method, url, kw in [
        ("get", f"/api/documents/{doc['id']}", {}),
        ("get", f"/api/documents/{doc['id']}/chunks", {}),
        ("get", f"/api/documents/{doc['id']}/file", {}),
        ("delete", f"/api/documents/{doc['id']}", {}),
        ("post", "/api/tutor/ask", {"json": {"question": "What is Little's Law?", "document_ids": [doc["id"]]}}),
        ("post", "/api/quizzes", {"json": {"document_ids": [doc["id"]]}}),
        ("get", f"/api/quizzes/{quiz['id']}", {}),
        ("post", f"/api/questions/{qid}/attempts", {"json": {"selected_index": 0}}),
    ]:
        r = getattr(client, method)(url, headers=intruder, **kw)
        assert r.status_code == 404, (method, url, r.status_code)
    assert client.get("/api/documents", headers=intruder).json() == []
    assert client.get(f"/api/documents/{doc['id']}", headers=owner).status_code == 200


def test_auth_required_and_bad_login(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents", headers={"Authorization": "Bearer garbage"}).status_code == 401
    _signup(client, "bob@example.com")
    assert client.post("/api/auth/login", json={"email": "bob@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "BOB@example.com", "password": "correct-horse-1"}).status_code == 200
    assert client.post("/api/auth/signup", json={"email": "bob@example.com", "password": "another-pass-1"}).status_code == 409


def test_account_deletion_removes_everything(client, sample_pdf):
    h = _signup(client, "carol@example.com")
    user_id = client.get("/api/auth/me", headers=h).json()["id"]
    _upload(client, h, sample_pdf)
    # Settings are cached per process, so in a full run another test file's STORAGE_DIR may apply.
    user_dir = os.path.join(get_settings().storage_dir, user_id)
    assert os.listdir(user_dir), "file should be stored"
    assert client.delete("/api/auth/me", headers=h).status_code == 204
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert os.listdir(user_dir) == [], "stored files must be deleted with the account"
