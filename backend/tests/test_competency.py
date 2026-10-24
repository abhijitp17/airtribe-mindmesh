"""Competency -> concept links: rules, model fallback, skip-when-unchanged, study links on a prep."""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_competency.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models_kg import KgEdge  # noqa: E402
from app.services import competency as comp  # noqa: E402
from app.services.graph import rebuild_graph  # noqa: E402
from tests.conftest import make_pdf  # noqa: E402
from tests.test_interview_samples import SAMPLE_JD, SAMPLE_RESUME  # noqa: E402

IV = "/api/interview"
BODY = "This section explains the method with worked examples, common mistakes and how to check your results."


def material_pdf() -> bytes:
    pages = []
    for i, title in enumerate(["Demand forecasting", "Statistical modelling", "Stakeholder communication",
                               "Inventory policy"], start=1):
        pages.append([f"{i}. {title}", "", f"{title} is covered here. " + BODY] + [BODY] * 6)
    return make_pdf(pages)


@pytest.mark.parametrize("skill, concept, expected", [
    ("Demand forecasting", "Demand forecasting", True),
    ("Demand forecasting", "Forecasting", True),
    ("SQL", "SQL joins", True),
    ("Key performance indicators", "KPIs", True),
    ("Python", "Pythons", True),
    ("Demand forecasting", "Inventory policy", False),
    ("People management", "Statistical modelling", False),
    ("A", "A team", False),  # too short to mean anything
])
def test_rule_match(skill, concept, expected):
    assert comp.rule_match(skill, concept) is expected


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _setup(client, email):
    h = _signup(client, email)
    r = client.post("/api/documents?rights_confirmed=true", headers=h,
                    files={"file": ("m.pdf", material_pdf(), "application/pdf")})
    assert r.status_code == 201
    resume = client.post(f"{IV}/resumes", headers=h, json={"text": SAMPLE_RESUME}).json()
    job = client.post(f"{IV}/jobs", headers=h, json={"text": SAMPLE_JD}).json()
    prep = client.post(f"{IV}/preps", headers=h, json={"resume_id": resume["id"], "job_id": job["id"]}).json()
    me = client.get("/api/auth/me", headers=h).json()["id"]
    return h, prep, me, r.json()["id"]


def test_prep_shows_where_each_skill_is_taught(client):
    h, prep, me, doc_id = _setup(client, "c1@example.com")
    links = client.get(f"{IV}/preps/{prep['id']}/study-links", headers=h).json()
    skills = {s["id"]: s["name"] for s in prep["skills"]}
    named = {skills[k]: v for k, v in links.items()}
    forecasting = next(v for k, v in named.items() if "forecast" in k.lower())
    assert forecasting[0]["concept"].lower().startswith("demand forecasting")
    assert forecasting[0]["document_id"] == doc_id and forecasting[0]["page"] == 1 and forecasting[0]["verified"]
    with SessionLocal() as db:
        edges = db.scalars(select(KgEdge).where(KgEdge.owner_id == me, KgEdge.rel == comp.MAPS_TO)).all()
    assert edges and all(e.source in ("rule", "model") for e in edges)
    # Another user can't read them.
    h2 = _signup(client, "c2@example.com")
    assert client.get(f"{IV}/preps/{prep['id']}/study-links", headers=h2).status_code == 404


def test_rebuild_skips_when_nothing_changed(client, monkeypatch):
    _h, _prep, me, _doc = _setup(client, "c3@example.com")
    calls = []
    real = comp._model_links
    monkeypatch.setattr(comp, "_model_links", lambda *a: calls.append(1) or real(*a))
    assert rebuild_graph(me)["maps_to"] == -1
    assert calls == []


def test_model_failure_leaves_the_signature_unset_so_it_retries(client, monkeypatch):
    _h, _prep, me, _doc = _setup(client, "c4@example.com")
    with SessionLocal() as db:
        from app.models_kg import KgNode
        db.scalar(select(KgNode).where(KgNode.owner_id == me, KgNode.kind == "meta")).name = "stale"
        db.commit()

    def broken(*a):
        raise ValueError("bad JSON")
    monkeypatch.setattr(comp, "_model_links", broken)
    assert rebuild_graph(me)["maps_to"] == 0
    with SessionLocal() as db:
        from app.models_kg import KgNode
        assert db.scalar(select(KgNode).where(KgNode.owner_id == me, KgNode.kind == "meta")).name == "stale"
