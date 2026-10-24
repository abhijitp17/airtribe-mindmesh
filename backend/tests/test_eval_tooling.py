"""Real-PDF eval tooling: draft gold sets, refuse unfinished ones, compare model pairs (offline)."""
import json
import shutil
import uuid

import pytest

from evals import compare_models
from evals.corpus import EVALS_DIR, load_doc
from evals.dataset import GoldSetError, QuizConfig, load_gold
from evals.make_gold import draft
from evals.run import make_provider, run_eval


@pytest.fixture
def private_pdf(sample_pdf):
    d = EVALS_DIR / "private" / f"test-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    (d / "factory.pdf").write_bytes(sample_pdf)
    yield f"{d.relative_to(EVALS_DIR)}/factory.pdf"
    shutil.rmtree(d)


def test_real_pdfs_load_through_the_production_pipeline(private_pdf):
    doc = load_doc(private_pdf)
    assert doc.page_count == 2 and doc.chunks and doc.chunks[0].page_start == 1


def test_draft_gold_must_be_finished_before_it_runs(private_pdf, tmp_path):
    cases = draft(private_pdf)
    answerable = [c for c in cases if c["expect"] == "answer"]
    assert answerable and all(c["must_cite_pages"] and "TODO" in c["question"] and c["_hint"] for c in answerable)
    assert sum(c["expect"] == "not_found" for c in cases) == 2

    gold = tmp_path / "draft.jsonl"
    gold.write_text("\n".join(json.dumps(c) for c in cases))
    with pytest.raises(GoldSetError, match="TODO"):
        load_gold(gold)

    for c in answerable:  # a human fills in the draft
        c["question"], c["key_facts"] = "What does Little's Law state?", ["throughput"]
    gold.write_text("\n".join(json.dumps(c) for c in cases[:1] + cases[-2:]))
    loaded = load_gold(gold)
    report = run_eval(make_provider("mock"), loaded, QuizConfig(1, "medium", ()), 6, {})
    assert report["metrics"]["citation_validity_rate"] == 1.0 and report["metrics"]["not_found_recall"] == 1.0


def test_compare_models_reports_a_verdict(monkeypatch, capsys):
    monkeypatch.setattr(compare_models, "make_provider", lambda name: make_provider("mock"))
    code = compare_models.main(["--candidate", "claude-sonnet-5-5", "claude-haiku-5-5", "--docs", "docs/operations.txt"])
    out = capsys.readouterr().out
    assert code == 0 and "RECOMMEND the candidate" in out and "citation_validity_rate" in out


def test_compare_models_needs_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        compare_models.main(["--candidate", "claude-sonnet-5-5", "claude-haiku-5-5", "--docs", "docs/operations.txt"])
