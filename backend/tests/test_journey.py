"""Notebook cover (GET /api/me/journey) and the first-run sample (POST /api/documents/sample)."""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{tmp}/t.db", "STORAGE_DIR": tmp, "AI_PROVIDER": "mock"})


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_new_user_starts_at_learn_with_nothing_to_resume(client):
    h = _signup(client, "j1@example.com")
    j = client.get("/api/me/journey", headers=h).json()
    assert [s["key"] for s in j["stages"]] == ["learn", "practise", "prove", "interview"]
    assert not any(s["done"] for s in j["stages"]) and j["current"] == "learn"
    assert j["resume"] is None and j["goals"] == [] and j["next_note"]
    assert all(s["href"].startswith("/") for s in j["stages"])  # every stop links somewhere: nothing is locked
    assert client.get("/api/me/journey").status_code == 401


def test_sample_fills_the_first_stop_and_the_map(client):
    h = _signup(client, "j2@example.com")
    r = client.post("/api/documents/sample", headers=h)
    assert r.status_code == 201 and r.json()["title"].startswith("How Learning Sticks")
    assert client.post("/api/documents/sample", headers=h).json()["id"] == r.json()["id"]  # idempotent
    j = client.get("/api/me/journey", headers=h).json()
    assert j["stages"][0]["done"] and j["current"] == "practise"
    assert j["resume"] == {"kind": "document", "title": f"Open {r.json()['title']}", "href": f"/documents/{r.json()['id']}"}
    g = client.get("/api/me/graph", headers=h).json()
    assert len(g["nodes"]) >= 5 and g["edges"], "the sample chapter's ideas build on each other"


def test_unfinished_quiz_is_where_you_left_off(client):
    h = _signup(client, "j3@example.com")
    doc = client.post("/api/documents/sample", headers=h).json()
    quiz = client.post("/api/quizzes", headers=h, json={"document_ids": [doc["id"]], "num_questions": 3}).json()
    q = quiz["questions"][0]
    body = {"selected_index": 0} if q.get("options") else {"response_text": "An answer from memory."}
    assert client.post(f"/api/questions/{q['id']}/attempts", headers=h, json=body).status_code in (200, 201)
    j = client.get("/api/me/journey", headers=h).json()
    assert j["resume"]["kind"] == "quiz" and j["resume"]["href"] == f"/quiz/{quiz['id']}"
    assert j["stages"][1]["detail"] == "1 answer"
