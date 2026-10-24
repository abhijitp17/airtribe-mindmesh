"""Knowledge tracing: behaviour, the comparison eval, parameter fitting, merged concepts in progress."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_kt.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

from app.core.mastery import P_INIT, AttemptEvidence, estimate, knowledge_trace  # noqa: E402

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def ev(score, qtype="mcq", diff="medium", days_ago=0):
    return AttemptEvidence(score, qtype, diff, NOW - timedelta(days=days_ago))


def test_correct_answers_raise_it_and_harder_evidence_counts_more():
    assert knowledge_trace([ev(1.0)], NOW) > P_INIT
    mcq = knowledge_trace([ev(1.0, "mcq")] * 2, NOW)
    applied = knowledge_trace([ev(1.0, "applied")] * 2, NOW)
    assert applied > mcq, "a right applied answer is harder to guess"
    assert knowledge_trace([ev(1.0, diff="hard")], NOW) > knowledge_trace([ev(1.0, diff="easy")], NOW)


def test_partial_credit_is_partial_evidence():
    full, half, none = (knowledge_trace([ev(s, "short")] * 2, NOW) for s in (1.0, 0.5, 0.0))
    assert full > half > none


def test_order_matters_recent_evidence_wins():
    improving = [ev(0.0, days_ago=3), ev(0.0, days_ago=2), ev(1.0, days_ago=1), ev(1.0)]
    slipping = [ev(1.0, days_ago=3), ev(1.0, days_ago=2), ev(0.0, days_ago=1), ev(0.0)]
    assert knowledge_trace(improving, NOW) > knowledge_trace(slipping, NOW)


def test_unpractised_knowledge_fades_towards_the_prior_but_is_not_lost_quickly():
    fresh = knowledge_trace([ev(1.0, "applied")] * 3, NOW)
    month = knowledge_trace([ev(1.0, "applied", days_ago=30)] * 3, NOW)
    year = knowledge_trace([ev(1.0, "applied", days_ago=365)] * 3, NOW)
    assert fresh > month > year > P_INIT - 1e-9
    assert estimate("x", [ev(1.0, "applied", days_ago=30)] * 3, now=NOW).level == "strong"


def test_eval_knowledge_tracing_beats_the_rules():
    from evals.mastery_eval import evaluate, simulate

    res = evaluate(simulate(150, seed=3))
    assert res["bkt"]["log_loss"] < res["rules"]["log_loss"]
    assert res["bkt"]["auc"] > res["rules"]["auc"]


def test_fit_recovers_a_better_setting_than_a_bad_one():
    from app.tools.fit_mastery import fit, log_loss
    from evals.mastery_eval import simulate

    seqs = [[a for a, _ in s] for s in simulate(120, seed=5)]
    pi, pl, ll = fit(seqs)
    assert ll <= log_loss(seqs, 0.5, 0.4) and ll <= log_loss(seqs, 0.05, 0.05)


def test_progress_counts_merged_concepts_as_one(client, sample_pdf):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Question
    from app.services.graph import merge_concepts
    from app.services.knowledge_graph import upsert_concepts

    r = client.post("/api/auth/signup", json={"email": "kt@example.com", "password": "correct-horse-1"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    me = r.json()["user"]["id"]
    doc = client.post("/api/documents?rights_confirmed=true", headers=h,
                      files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()["id"]
    quiz = client.post("/api/quizzes", headers=h, json={"document_ids": [doc], "count": 4}).json()
    ids = [q["id"] for q in quiz["questions"]]
    with SessionLocal() as db:
        for i, qid in enumerate(ids):
            db.get(Question, qid).concept = "WIP" if i % 2 else "Work in process"
        upsert_concepts(db, me, ["WIP", "Work in process"])
        merge_concepts(db, me)
        db.commit()
    for q in quiz["questions"]:
        body = {"selected_index": q.get("correct_index") or 0} if q["qtype"] == "mcq" else {"answer_text": "x"}
        client.post(f"/api/questions/{q['id']}/attempts", headers=h, json=body)
    names = [c["concept"] for c in client.get("/api/progress", headers=h).json()["concepts"]]
    assert "Work in process" in names and "WIP" not in names
