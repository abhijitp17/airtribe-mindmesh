"""Shared skill taxonomy: curated data integrity, matching, per-user links, the skill profile."""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{tmp}/t.db", "STORAGE_DIR": tmp, "AI_PROVIDER": "mock"})

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.concept_merge import stem_key  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models_kg import KgNode  # noqa: E402
from app.services import taxonomy as tx  # noqa: E402
from tests.test_competency import material_pdf  # noqa: E402
from tests.test_interview_samples import SAMPLE_JD, SAMPLE_RESUME  # noqa: E402


def test_taxonomy_data_is_consistent():
    skills = tx.load()["skills"]
    slugs = [s["slug"] for s in skills]
    assert len(slugs) == len(set(slugs))
    owner: dict[str, str] = {}
    for s in skills:
        assert s["category"] in {"technical", "tool", "domain", "behavioral"}
        for k in s["_keys"]:
            assert owner.setdefault(k, s["slug"]) == s["slug"], f"'{k}' belongs to two skills"


@pytest.mark.parametrize("name, slug", [
    ("Demand forecasting", "forecasting"), ("SQL joins", "sql"), ("WIP", "littles-law"), ("EOQ", "inventory-management"),
    ("Proven people management", "people-management"), ("Tableau", "data-visualisation"), ("Basket weaving", None), ("", None),
])
def test_match(name, slug):
    assert tx.match(name) == slug


def test_profile_combines_concepts_job_skills_roles_and_mastery(client):
    r = client.post("/api/auth/signup", json={"email": "tx@example.com", "password": "correct-horse-1"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    me = r.json()["user"]["id"]
    assert client.post("/api/documents?rights_confirmed=true", headers=h,
                       files={"file": ("m.pdf", material_pdf(), "application/pdf")}).status_code == 201
    resume = client.post("/api/interview/resumes", headers=h, json={"text": SAMPLE_RESUME}).json()
    job = client.post("/api/interview/jobs", headers=h, json={"text": SAMPLE_JD}).json()
    assert client.post("/api/interview/preps", headers=h, json={"resume_id": resume["id"], "job_id": job["id"]}).status_code == 201
    prof = client.get("/api/me/skill-profile", headers=h).json()
    fc = next(s for s in prof if s["slug"] == "forecasting")
    assert any("forecasting" in c.lower() for c in fc["concepts"]) and fc["job_skills"] and fc["roles"]
    assert fc["level"] in ("unverified", "weak", "developing", "strong")
    # Taxonomy nodes live in the user's own graph only.
    with SessionLocal() as db:
        assert {n.owner_id for n in db.scalars(select(KgNode).where(KgNode.kind == "taxonomy"))} == {me}
    r2 = client.post("/api/auth/signup", json={"email": "tx2@example.com", "password": "correct-horse-1"})
    other = {"Authorization": f"Bearer {r2.json()['token']}"}
    assert client.get("/api/me/skill-profile", headers=other).json() == []
    lst = client.get("/api/taxonomy", headers=other).json()
    assert len(lst["skills"]) >= 30 and all("_keys" not in s for s in lst["skills"])
