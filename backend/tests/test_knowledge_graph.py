"""Knowledge graph foundation (app/models_kg.py, app/services/knowledge_graph.py)."""
import os
import tempfile
import time
from datetime import date, timedelta

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_kg.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.core.planner import TopicSpec  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models_kg import KgEdge, KgNode  # noqa: E402
from app.services.knowledge_graph import canonical_key, prerequisite_chain, record_prerequisites, upsert_concepts  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    return h, client.get("/api/auth/me", headers=h).json()["id"]


def _upload(client, h, pdf):
    doc_id = client.post("/api/documents?rights_confirmed=true", headers=h,
                         files={"file": ("fp.pdf", pdf, "application/pdf")}).json()["id"]
    for _ in range(50):
        if client.get(f"/api/documents/{doc_id}", headers=h).json()["status"] == "ready":
            return doc_id
        time.sleep(0.05)
    raise AssertionError("processing did not finish")


def _count(model, owner_id):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model).where(model.owner_id == owner_id))


def test_canonical_key():
    assert canonical_key("Little's Law") == canonical_key("littles  law") == canonical_key("LITTLE’S LAW.") == "littles law"
    assert canonical_key("C++") != canonical_key("C") and canonical_key("C#") == "c#"
    assert canonical_key("कार्यशील पूंजी") == "कार्यशील पूंजी"  # Devanagari vowel signs are kept
    assert canonical_key("  ") == ""


def test_goal_saves_prerequisite_edges_idempotently(client, sample_pdf):
    h, uid = _signup(client, "kg-plan@example.com")
    doc = _upload(client, h, sample_pdf)
    deadline = (date.today() + timedelta(days=21)).isoformat()
    g = client.post("/api/goals", headers=h, json={"goal_type": "learn", "title": "Factory physics", "deadline": deadline,
                                                   "minutes_per_day": 45, "study_days": [0, 1, 2, 3, 4, 5, 6],
                                                   "document_ids": [doc]}).json()
    nodes, edges = _count(KgNode, uid), _count(KgEdge, uid)  # includes the document's "covers" edges
    assert nodes >= 2 and edges >= 1, (nodes, edges)
    with SessionLocal() as db:
        prereqs = db.scalars(select(KgEdge).where(KgEdge.owner_id == uid, KgEdge.rel == "prerequisite_of")).all()
        assert prereqs
        # Planner guesses carry the goal and stay unverified; edges the document already grounded (with a
        # quote) aren't duplicated by the planner.
        for e in prereqs:
            assert (e.source == "planner" and not e.verified and e.provenance["goal_id"] == g["id"]) or \
                   (e.source == "document" and e.verified and e.provenance["quote"])

    # Regenerating proposes the same topics again: no duplicate nodes or edges.
    assert client.post(f"/api/goals/{g['id']}/regenerate", headers=h).status_code == 200
    assert (_count(KgNode, uid), _count(KgEdge, uid)) == (nodes, edges)


def test_quiz_concepts_become_nodes(client, sample_pdf):
    h, uid = _signup(client, "kg-quiz@example.com")
    doc = _upload(client, h, sample_pdf)
    quiz = client.post("/api/quizzes", headers=h, json={"document_ids": [doc], "count": 4}).json()
    with SessionLocal() as db:
        keys = set(db.scalars(select(KgNode.canonical_key).where(KgNode.owner_id == uid)).all())
    assert {canonical_key(q["concept"]) for q in quiz["questions"]} <= keys


def test_prerequisite_chain_is_ordered_and_survives_cycles(client):
    _h, uid = _signup(client, "kg-chain@example.com")
    _h2, other = _signup(client, "kg-other@example.com")
    topics = [TopicSpec(topic="Basics", concept="Flow basics"),
              TopicSpec(topic="Little", concept="Little's Law", prerequisites=["Basics"]),
              TopicSpec(topic="Queues", concept="Queueing", prerequisites=["Little"])]
    with SessionLocal() as db:
        assert record_prerequisites(db, uid, topics, {"goal_id": "g1"}) == 2
        # A later plan that orders things the other way round creates a cycle.
        assert record_prerequisites(db, uid, [TopicSpec(topic="Q", concept="queueing"),
                                              TopicSpec(topic="B", concept="Flow Basics", prerequisites=["Q"])], {}) == 1
        db.commit()
        assert prerequisite_chain(db, uid, "queueing") == [("Little's Law", 1), ("Flow basics", 2)]
        assert prerequisite_chain(db, uid, "Flow basics")[0] == ("Queueing", 1)  # terminates despite the cycle
        assert prerequisite_chain(db, other, "Queueing") == []  # another user's graph is invisible
        assert prerequisite_chain(db, uid, "unknown concept") == []


def test_upsert_is_idempotent_and_account_deletion_removes_graph(client):
    h, uid = _signup(client, "kg-leaver@example.com")
    with SessionLocal() as db:
        a = upsert_concepts(db, uid, ["Little's Law", "littles law", "Variability", ""])
        b = upsert_concepts(db, uid, ["LITTLE'S LAW"])
        assert len(a) == 2 and a["littles law"].id == b["littles law"].id
        record_prerequisites(db, uid, [TopicSpec(topic="V", concept="Variability"),
                                       TopicSpec(topic="L", concept="Little's Law", prerequisites=["V"])], {})
        db.commit()
    assert _count(KgEdge, uid) == 1
    # The graph is the user's data: it is in their export...
    export = client.get("/api/account/export", headers=h)
    assert export.status_code == 200
    assert '"kg_nodes"' in export.text and '"kg_edges"' in export.text and "Little's Law" in export.text
    # ...and goes with their account.
    assert client.delete("/api/auth/me", headers=h).status_code == 204
    assert _count(KgNode, uid) == 0 and _count(KgEdge, uid) == 0
