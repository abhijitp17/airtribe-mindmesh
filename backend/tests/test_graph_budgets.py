"""Graph query time budgets (P2): the per-request graph work stays fast on a large personal graph.

Budgets (docs/slo.md) are for one user's graph of 2,000 concepts and ~6,000 edges on SQLite, with
headroom for slow CI machines. Postgres is faster for the recursive query.
"""
import os
import random
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{tmp}/t.db", "STORAGE_DIR": tmp, "AI_PROVIDER": "mock"})

import pytest  # noqa: E402

from app.core.planner import TopicSpec  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.models_kg import KgEdge, KgNode  # noqa: E402
from app.services.graph import concept_aliases, graph_hints  # noqa: E402
from app.services.knowledge_graph import canonical_key, prerequisite_chain, with_graph_prerequisites  # noqa: E402

N_CONCEPTS = 2000
BUDGET_MS = {"prerequisite_chain": 150, "concept_aliases": 400, "graph_hints": 600, "plan_ordering": 150}


@pytest.fixture
def big_graph(client):
    rng = random.Random(1)
    with SessionLocal() as db:
        u = User(email="big@example.com", password_hash="x", display_name="")
        db.add(u)
        db.flush()
        nodes = [KgNode(owner_id=u.id, kind="concept", name=f"Concept {i}", canonical_key=canonical_key(f"Concept {i}"))
                 for i in range(N_CONCEPTS)]
        docs = [KgNode(owner_id=u.id, kind="document", name=f"Doc {d}", canonical_key=f"doc{d}") for d in range(10)]
        db.add_all(nodes + docs)
        db.flush()
        for n in nodes[1500:1700]:  # 10% merged away
            n.merged_into_id = nodes[rng.randrange(0, 1500)].id
        pairs = {(rng.randrange(N_CONCEPTS), rng.randrange(N_CONCEPTS)) for _ in range(4000)}
        db.add_all(KgEdge(owner_id=u.id, src_id=nodes[a].id, dst_id=nodes[b].id, rel="prerequisite_of", source="document",
                          verified=True, provenance={}) for a, b in pairs if a != b)
        db.add_all(KgEdge(owner_id=u.id, src_id=docs[i % 10].id, dst_id=n.id, rel="covers", source="model", verified=True,
                          provenance={"document_id": f"doc{i % 10}", "chunk_id": f"c{i}", "page": 1}) for i, n in enumerate(nodes))
        db.commit()
        return u.id


def _ms(fn):
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def test_graph_queries_stay_within_budget(big_graph):
    uid = big_graph
    with SessionLocal() as db:
        _ms(lambda: prerequisite_chain(db, uid, "Concept 7"))  # warm up
        took = {
            "prerequisite_chain": max(_ms(lambda: prerequisite_chain(db, uid, f"Concept {i}")) for i in (3, 500, 1499)),
            "concept_aliases": _ms(lambda: concept_aliases(db, uid)),
            "graph_hints": _ms(lambda: graph_hints(db, uid, [f"doc{d}" for d in range(10)])),
            "plan_ordering": _ms(lambda: with_graph_prerequisites(
                db, uid, [TopicSpec(topic=f"Concept {i}", concept=f"Concept {i}") for i in range(0, 40)])),
        }
    print("graph query ms:", {k: round(v, 1) for k, v in took.items()})
    over = {k: round(v) for k, v in took.items() if v > BUDGET_MS[k]}
    assert not over, f"over budget (ms): {over}; all: { {k: round(v) for k, v in took.items()} }"
