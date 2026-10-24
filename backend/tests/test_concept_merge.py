"""Concept merging: rules (gold-gated), storage, aliases, model confirmation, the rebuild job."""
import json
import os
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_concept_merge.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core import concept_merge as cm  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.models_kg import KgEdge, KgNode  # noqa: E402
from app.services import graph  # noqa: E402
from app.services.knowledge_graph import canonical_key, prerequisite_chain, record_prerequisites, upsert_concepts  # noqa: E402
from app.core.planner import TopicSpec  # noqa: E402

GOLD = Path(__file__).resolve().parents[1] / "evals" / "gold" / "concept_merges.jsonl"


# ---------------------------------------------------------------- rules

def test_rules_are_precise_on_the_gold_set():
    rows = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]
    got = [(bool(cm.rule_pairs([g["a"], g["b"]])), g["same"], g) for g in rows]
    false_merges = [g for merged, same, g in got if merged and not same]
    missed = [g for merged, same, g in got if same and not merged]
    assert false_merges == [], "a wrong merge corrupts mastery and prerequisites"
    assert len(missed) <= len(rows) * 0.1, missed


@pytest.mark.parametrize("word, expected", [("queues", "queue"), ("inventories", "inventory"), ("processes", "process"),
                                           ("analysis", "analysis"), ("status", "status"), ("sizes", "size"),
                                           ("boxes", "box"), ("bus", "bus"), ("ml", "ml")])
def test_singular(word, expected):
    assert cm.singular(word) == expected


def test_ambiguous_acronym_goes_to_the_model_not_a_rule():
    names = ["CV", "Coefficient of variation", "Curriculum vitae"]
    assert cm.rule_pairs(names) == []
    assert {(p.a, p.b) for p in cm.similar_pairs(names)} >= {("CV", "Coefficient of variation"), ("CV", "Curriculum vitae")}


def test_pick_canonical_prefers_evidence_then_the_spelled_out_singular_form():
    assert cm.pick_canonical("WIP", "Work in process") == ("Work in process", "WIP")
    assert cm.pick_canonical("Queues", "Queue") == ("Queue", "Queues")
    assert cm.pick_canonical("Work in process (WIP)", "Work in process") == ("Work in process", "Work in process (WIP)")
    assert cm.pick_canonical("WIP", "Work in process", {canonical_key("WIP"): 5}) == ("WIP", "Work in process")


# ---------------------------------------------------------------- storage

@pytest.fixture
def owner(client):  # `client` resets the database
    with SessionLocal() as db:
        u = User(email="m@example.com", password_hash="x", display_name="")
        db.add(u)
        db.commit()
        return u.id


def _node(db, owner_id, name):
    return db.scalar(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.canonical_key == canonical_key(name)))


def test_merge_moves_edges_and_keeps_an_audit_trail(owner):
    with SessionLocal() as db:
        record_prerequisites(db, owner, [TopicSpec(topic="Flow", concept="Flow basics"),
                                         TopicSpec(topic="WIP", concept="WIP", prerequisites=["Flow"]),
                                         TopicSpec(topic="Little", concept="Little's Law", prerequisites=["WIP"]),
                                         TopicSpec(topic="Work in process", concept="Work in process", prerequisites=["Flow"])], {})
        db.commit()
        out = graph.merge_concepts(db, owner)
        db.commit()
        assert out["rule"] == 1
        wip, full = _node(db, owner, "WIP"), _node(db, owner, "Work in process")
        assert wip.merged_into_id == full.id
        edges = db.scalars(select(KgEdge).where(KgEdge.owner_id == owner)).all()
        assert not any(wip.id in (e.src_id, e.dst_id) for e in edges if e.rel == "prerequisite_of")
        same = [e for e in edges if e.rel == "same_as"]
        assert len(same) == 1 and same[0].provenance == {"reason": "acronym"} and same[0].verified
        # The duplicate Flow -> (WIP | Work in process) edge became one edge; the chain still works.
        assert [n for n, _ in prerequisite_chain(db, owner, "Little's Law")] == ["Work in process", "Flow basics"]
        # Idempotent.
        assert graph.merge_concepts(db, owner) == {"rule": 0, "model": 0}


def test_aliases_and_new_mentions_resolve_to_the_kept_concept(owner):
    with SessionLocal() as db:
        upsert_concepts(db, owner, ["Queues", "Queue", "Little's Law"])
        graph.merge_concepts(db, owner)
        db.commit()
        aliases = graph.concept_aliases(db, owner)
        assert aliases[canonical_key("Queues")] == aliases[canonical_key("Queue")] == "Queue"
        assert graph.canonical_concept("queues", aliases) == "Queue"
        assert upsert_concepts(db, owner, ["Queues"])[canonical_key("Queues")].name == "Queue"


def test_chained_merges_resolve(owner):
    with SessionLocal() as db:
        upsert_concepts(db, owner, ["Net present values", "Net present value", "NPV"])
        graph.merge_concepts(db, owner)
        db.commit()
        aliases = graph.concept_aliases(db, owner)
        assert {aliases[canonical_key(n)] for n in ("Net present values", "Net present value", "NPV")} == {"Net present value"}


def test_model_confirms_similar_pairs_and_remembers_no(owner):
    from app.deps import user_gateway

    with SessionLocal() as db:
        upsert_concepts(db, owner, ["Demand forecasting", "Forecasting demand", "Cash flow", "Cash flow statement"])
        db.commit()
        out = graph.merge_concepts(db, owner, user_gateway(owner, db))
        db.commit()
        assert out["model"] == 1
        assert _node(db, owner, "Forecasting demand").merged_into_id or _node(db, owner, "Demand forecasting").merged_into_id
        assert _node(db, owner, "Cash flow").merged_into_id is None
        assert db.scalars(select(KgEdge).where(KgEdge.rel == "not_same")).all(), "a 'no' is remembered"
        calls = []
        real = graph._model_confirm
        graph._model_confirm = lambda *a: calls.append(a) or real(*a)
        try:
            graph.merge_concepts(db, owner, user_gateway(owner, db))
        finally:
            graph._model_confirm = real
        assert calls == [], "pairs already decided aren't asked again"


def test_rebuild_job_runs_after_a_quiz(client, sample_pdf):
    r = client.post("/api/auth/signup", json={"email": "rb@example.com", "password": "correct-horse-1"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    doc = client.post("/api/documents?rights_confirmed=true", headers=h,
                      files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()["id"]
    assert client.post("/api/quizzes", headers=h, json={"document_ids": [doc], "count": 3}).status_code == 201
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == "rb@example.com"))
        assert db.scalars(select(KgNode).where(KgNode.owner_id == uid, KgNode.kind == "concept")).all()
