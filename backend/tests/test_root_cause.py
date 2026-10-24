"""Root-cause practice (prerequisite-first sessions) and plans ordered by the knowledge graph."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_root_cause.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

from sqlalchemy import select  # noqa: E402

from app.core import session_builder as sb  # noqa: E402
from app.core.planner import TopicSpec, topological_order  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Attempt, Question, Quiz, User  # noqa: E402
from app.models_kg import KgEdge  # noqa: E402
from app.services import engagement  # noqa: E402
from app.services.knowledge_graph import PREREQUISITE_OF, upsert_concepts, with_graph_prerequisites  # noqa: E402


# ---------------------------------------------------------------- pure builder

def test_root_causes_come_first_and_explain_themselves():
    inp = sb.BuilderInput(
        due_reviews=[sb.DueReview("Little's Law", 2, "weak", ["d1"])],
        root_causes=[sb.RootCause("Work in process", "Little's Law", "unverified", True, ["d1"]),
                     sb.RootCause("Throughput", "Kanban", "weak", False, ["d1"]),
                     sb.RootCause("Flow basics", "Queues", "weak", False, ["d1"])],
        documents=[sb.DocRef("d1", "Notes")])
    steps = sb.build_session(15, inp)
    assert [s["title"] for s in steps[:2]] == ["Practise Work in process first", "Practise Throughput first"]
    assert "Little's Law builds on Work in process (your material says so)" in steps[0]["detail"]
    assert "hasn't been tested yet" in steps[0]["detail"] and "is shaky" in steps[1]["detail"]
    assert steps[2]["title"] == "Review Little's Law"  # then the weak concept itself
    assert sum(1 for s in steps if s["title"].endswith(" first")) == sb.MAX_ROOT_CAUSES
    five = sb.build_session(5, inp)
    assert [s["title"] for s in five] == ["Practise Work in process first"]


# ---------------------------------------------------------------- Today, end to end

def _user_with_material(client, sample_pdf, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    doc = client.post("/api/documents?rights_confirmed=true", headers=h,
                      files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()["id"]
    return h, r.json()["user"]["id"], doc


def _answers(db, owner, doc, concept, scores):
    quiz = Quiz(owner_id=owner, document_ids=[doc], title="t")
    db.add(quiz)
    db.flush()
    now = datetime.now(timezone.utc)
    for i, s in enumerate(scores):
        q = Question(quiz_id=quiz.id, owner_id=owner, position=i, qtype="mcq", concept=concept, difficulty="medium",
                     prompt="p", options=["a", "b"], correct_index=0, answer_key="a", rubric=[], explanation="",
                     source_chunk_ids=[], generator_version="t")
        db.add(q)
        db.flush()
        db.add(Attempt(owner_id=owner, question_id=q.id, selected_index=0, verdict="correct" if s else "incorrect",
                       score=s, feedback="", criteria=[], evaluator_version="t", created_at=now - timedelta(minutes=10 - i)))


def test_today_practises_the_weak_prerequisite_first(client, sample_pdf):
    h, me, doc = _user_with_material(client, sample_pdf, "rc1@example.com")
    with SessionLocal() as db:
        nodes = upsert_concepts(db, me, ["Variability basics", "Queueing delay"])
        db.add(KgEdge(owner_id=me, src_id=nodes["variability basics"].id, dst_id=nodes["queueing delay"].id,
                      rel=PREREQUISITE_OF, source="document", verified=True, provenance={"quote": "q"}))
        _answers(db, me, doc, "Queueing delay", [0.0, 0.0, 0.0])  # weak
        db.commit()
        inp = engagement.builder_input(me, db)
    assert [(r.concept, r.for_concept, r.level, r.grounded) for r in inp.root_causes] == \
        [("Variability basics", "Queueing delay", "unverified", True)]
    first = client.get("/api/today/preview", headers=h).json()["suggestions"]["15"][0]
    assert first["title"] == "Practise Variability basics first" and first["target"]["document_ids"] == [doc]


def test_no_root_cause_when_the_prerequisite_is_known(client, sample_pdf):
    _h, me, doc = _user_with_material(client, sample_pdf, "rc2@example.com")
    with SessionLocal() as db:
        nodes = upsert_concepts(db, me, ["Variability basics", "Queueing delay"])
        db.add(KgEdge(owner_id=me, src_id=nodes["variability basics"].id, dst_id=nodes["queueing delay"].id,
                      rel=PREREQUISITE_OF, source="planner", verified=False, provenance={}))
        _answers(db, me, doc, "Queueing delay", [0.0, 0.0, 0.0])
        _answers(db, me, doc, "Variability basics", [1.0, 1.0, 1.0, 1.0])
        db.commit()
        assert engagement.builder_input(me, db).root_causes == []


# ---------------------------------------------------------------- plans

def test_plan_order_follows_grounded_edges_only(client):
    with SessionLocal() as db:
        u = User(email="plan@example.com", password_hash="x", display_name="")
        db.add(u)
        db.flush()
        n = upsert_concepts(db, u.id, ["Little's Law", "Work in process", "Kanban"])
        db.add(KgEdge(owner_id=u.id, src_id=n["work in process"].id, dst_id=n["littles law"].id,
                      rel=PREREQUISITE_OF, source="document", verified=True, provenance={}))
        db.add(KgEdge(owner_id=u.id, src_id=n["littles law"].id, dst_id=n["kanban"].id,
                      rel=PREREQUISITE_OF, source="planner", verified=False, provenance={}))  # a guess: ignored
        db.commit()
        topics = [TopicSpec(topic="Kanban", concept="Kanban"), TopicSpec(topic="Little's Law", concept="Little's Law"),
                  TopicSpec(topic="WIP", concept="Work in process")]
        out = with_graph_prerequisites(db, u.id, topics)
    assert [t.prerequisites for t in out] == [[], ["WIP"], []]
    assert topics[1].prerequisites == [], "the input isn't mutated"
    assert [t.topic for t in topological_order(out)] == ["Kanban", "WIP", "Little's Law"]
