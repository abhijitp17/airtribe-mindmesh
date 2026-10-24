"""Knowledge map (GET /api/me/graph): concepts, prerequisite edges, sources, mastery, isolation, cap."""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{tmp}/t.db", "STORAGE_DIR": tmp, "AI_PROVIDER": "mock"})

from app.db import SessionLocal  # noqa: E402
from app.models_kg import KgEdge, KgNode  # noqa: E402
from app.services.graph_view import knowledge_map  # noqa: E402
from app.services.knowledge_graph import PREREQUISITE_OF, canonical_key  # noqa: E402
from tests.test_competency import material_pdf  # noqa: E402


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]["id"]


def test_map_from_an_upload_traces_every_concept_to_its_source(client):
    h, _ = _signup(client, "map@example.com")
    assert client.get("/api/me/graph", headers=h).json() == {"nodes": [], "edges": [], "documents": [], "total_concepts": 0}
    doc = client.post("/api/documents?rights_confirmed=true", headers=h,
                      files={"file": ("m.pdf", material_pdf(), "application/pdf")}).json()
    g = client.get("/api/me/graph", headers=h).json()
    assert g["nodes"] and g["total_concepts"] >= len(g["nodes"])
    assert g["documents"] == [{"id": doc["id"], "title": doc["title"] or doc["filename"]}]
    with_source = [n for n in g["nodes"] if n["sources"]]
    assert with_source, "concepts extracted from a document are linked to it"
    for n in with_source:
        assert n["source_count"] >= len(n["sources"]) and n["level"] in ("unverified", "weak", "developing", "strong")
        assert all(s["document_id"] == doc["id"] and s["page"] for s in n["sources"])
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])

    # Someone else sees nothing of it.
    other, _ = _signup(client, "map2@example.com")
    assert client.get("/api/me/graph", headers=other).json()["nodes"] == []
    assert client.get("/api/me/graph").status_code == 401


def test_prerequisites_merges_cap_and_ranking(client):
    _, me = _signup(client, "map3@example.com")
    with SessionLocal() as db:
        def node(name, **kw):
            n = KgNode(owner_id=me, kind="concept", name=name, canonical_key=canonical_key(name), **kw)
            db.add(n)
            db.flush()
            return n
        a, b, c = node("Probability"), node("Bayes rule"), node("Naive Bayes")
        node("Bayes theorem", merged_into_id=b.id)  # folded into "Bayes rule": not a node of its own
        for i in range(5):
            node(f"Loose idea {i}")
        db.add_all([KgEdge(owner_id=me, src_id=a.id, dst_id=b.id, rel=PREREQUISITE_OF, source="model", verified=True),
                    KgEdge(owner_id=me, src_id=b.id, dst_id=c.id, rel=PREREQUISITE_OF, source="planner", verified=False)])
        db.commit()

        g = knowledge_map(db, me)
        names = [n["name"] for n in g["nodes"]]
        assert g["total_concepts"] == 8 and "Bayes theorem" not in names
        assert names[0] == "Bayes rule"  # best connected first
        assert {(e["source"], e["target"], e["verified"]) for e in g["edges"]} == {(a.id, b.id, True), (b.id, c.id, False)}

        small = knowledge_map(db, me, limit=2)
        assert len(small["nodes"]) == 2 and small["total_concepts"] == 8
        kept = {n["id"] for n in small["nodes"]}
        assert all(e["source"] in kept and e["target"] in kept for e in small["edges"])
