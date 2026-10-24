"""Eval harness: metric unit tests, loaders, corpus builder and a mock smoke run."""
import json
import tempfile
from pathlib import Path

import pytest

from evals.corpus import PAGE_BREAK, load_doc, parse_source, render_pdf
from evals.dataset import GoldSetError, load_gold, load_quiz_config, parse_case
from evals.metrics import (
    CaseOutcome,
    Delta,
    QuizOutcome,
    build_report,
    citation_page_accuracy,
    citation_validity_rate,
    compare,
    fact_present,
    key_fact_recall,
    not_found_precision,
    not_found_recall,
    question_validity_rate,
    quiz_yield,
    regressions,
    retrieval_recall_at_k,
)
from evals.run import DEFAULT_GOLD, DEFAULT_QUIZ, filter_docs, format_table, main, run_eval
from app.ai.mock import MockProvider


def _case(id="c", expect="answer", status="verified", answer="", pages=(1,), facts=(), cites=(), retrieved=(), doc="d"):
    return CaseOutcome(id, doc, expect, status, answer, tuple(pages), tuple(facts), tuple(cites), tuple(retrieved))


def _nf(id="n", status="not_found"):
    return _case(id, expect="not_found", status=status, pages=())


# ---- metrics ----

def test_citation_page_accuracy_counts_each_citation_and_spans():
    outcomes = [
        _case(pages=(2,), cites=((2, 2), (4, 4))),
        _case(pages=(3,), cites=((2, 3),)),  # span 2-3 covers page 3
        _nf(status="verified"),  # citations on not_found cases are not page-scored
    ]
    assert citation_page_accuracy(outcomes) == round(2 / 3, 4)


def test_citation_page_accuracy_undefined_without_citations():
    assert citation_page_accuracy([_case(cites=())]) is None


def test_citation_validity_rate_excludes_declines_and_penalises_unverified():
    outcomes = [_case(status="verified"), _case(status="partial"), _case(status="unverified"), _case(status="not_found")]
    assert citation_validity_rate(outcomes) == round(2 / 3, 4)
    assert citation_validity_rate([_nf()]) is None


def test_not_found_precision_and_recall():
    outcomes = [
        _nf("n1"),  # true positive
        _nf("n2", status="verified"),  # false negative: answered an off-topic question
        _case("a1", status="not_found"),  # false positive: declined a covered question
        _case("a2"),
    ]
    assert not_found_precision(outcomes) == 0.5
    assert not_found_recall(outcomes) == 0.5


def test_not_found_metrics_undefined_when_no_relevant_cases():
    assert not_found_precision([_case()]) is None
    assert not_found_recall([_case()]) is None


@pytest.mark.parametrize("fact, answer, expected", [
    ("cycle time", "Average Cycle-Time is three days.", True),
    ("standard deviation divided by the mean", "It is the standard deviation divided by the mean.", True),
    ("work in process", "Work-in-process equals throughput times cycle time.", True),
    ("utilizations", "utilization rises", True),  # stemmed
    ("divided by the mean", "the mean divided by", False),  # order matters
    ("1.65", "a z value of about 1.65", True),
    ("three days", "three or four days", False),
    ("", "anything", False),
])
def test_fact_present_uses_normalized_contiguous_tokens(fact, answer, expected):
    assert fact_present(fact, answer) is expected


def test_key_fact_recall_averages_per_case_and_scores_declines_zero():
    outcomes = [
        _case(answer="inventory and capacity", facts=("inventory", "capacity", "time")),  # 2/3
        _case(answer="", status="not_found", facts=("bottleneck",)),  # wrongly declined: 0
        _case(answer="anything", facts=()),  # no facts: excluded
        _nf(),  # excluded
    ]
    assert key_fact_recall(outcomes) == round((2 / 3 + 0) / 2, 4)


def test_retrieval_recall_at_k_and_top1():
    outcomes = [
        _case(pages=(3,), retrieved=((1, 1), (3, 3))),
        _case(pages=(2,), retrieved=((1, 2),)),
        _case(pages=(5,), retrieved=((1, 1),)),
        _nf(),
    ]
    assert retrieval_recall_at_k(outcomes) == round(2 / 3, 4)
    assert retrieval_recall_at_k(outcomes, 1) == round(1 / 3, 4)


def test_quiz_metrics():
    quizzes = [QuizOutcome("d", None, 5, 6, 4, 4), QuizOutcome("d", "x", 5, 4, 4, 5)]
    assert question_validity_rate(quizzes) == 0.8
    assert quiz_yield(quizzes) == 0.9
    assert question_validity_rate([QuizOutcome("d", None, 5, 0, 0, 0)]) is None


def test_build_report_has_overall_by_doc_and_cases():
    outcomes = [_case("a", doc="x", cites=((1, 1),), retrieved=((1, 1),)), _nf("n")]
    report = build_report(outcomes, [QuizOutcome("x", None, 3, 3, 3, 3)], {"provider": "test"})
    assert report["meta"] == {"provider": "test"}
    assert report["counts"] == {"cases": 2, "answerable": 1, "not_found": 1, "quizzes": 1, "generated_questions": 3}
    assert set(report["by_doc"]) == {"d", "x"}
    assert report["metrics"]["not_found_recall"] == 1.0
    assert report["cases"][0] == {"id": "a", "expect": "answer", "status": "verified", "cited_pages": [1],
                                  "retrieval_hit": True, "top1_hit": True, "fact_recall": None,
                                  "injection_resisted": None}
    json.dumps(report)  # serialisable


def test_compare_flags_drops_beyond_tolerance_and_lost_metrics():
    base = {"metrics": {"citation_validity_rate": 1.0, "not_found_recall": 0.5, "key_fact_recall": 0.6}}
    cur = {"metrics": {"citation_validity_rate": 0.99, "not_found_recall": 0.4, "key_fact_recall": None}}
    deltas = {d.metric: d for d in compare(cur, base)}
    assert deltas["citation_validity_rate"].change == -0.01
    bad = {d.metric for d in regressions(list(deltas.values()), tolerance=0.02)}
    assert bad == {"not_found_recall", "key_fact_recall"}
    assert not Delta("m", None, 0.1).regressed(0.0)  # newly defined metric is not a regression


# ---- loaders ----

def test_parse_case_validates_fields():
    ok = {"id": "x", "doc": "docs/a.txt", "question": "Q?", "expect": "answer", "must_cite_pages": [2], "key_facts": ["f"]}
    assert parse_case(ok, "t").level == "standard"
    with pytest.raises(GoldSetError, match="expect"):
        parse_case({**ok, "expect": "maybe"}, "t")
    with pytest.raises(GoldSetError, match="must_cite_page"):
        parse_case({**ok, "must_cite_pages": []}, "t")
    with pytest.raises(GoldSetError, match="not_found cases"):
        parse_case({**ok, "expect": "not_found"}, "t")
    with pytest.raises(GoldSetError, match="level"):
        parse_case({**ok, "level": "expert"}, "t")


def test_load_gold_rejects_duplicates_with_line_number():
    line = json.dumps({"id": "x", "doc": "d", "question": "Q?", "expect": "not_found"})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "g.jsonl"
        path.write_text(f"{line}\n\n{line}\n")
        with pytest.raises(GoldSetError, match="g.jsonl:3: duplicate"):
            load_gold(path)


def test_committed_gold_set_meets_coverage_requirements():
    cases = load_gold(DEFAULT_GOLD)
    assert len(cases) >= 30
    assert sum(c.expect == "not_found" for c in cases) >= 6
    assert {c.doc for c in cases} == {"docs/operations.txt", "docs/finance.txt"}
    cfg = load_quiz_config(DEFAULT_QUIZ)
    assert {r.doc for r in cfg.runs} == {"docs/operations.txt", "docs/finance.txt"}


# ---- corpus ----

def test_parse_source_splits_title_pages_and_paragraphs():
    doc = parse_source(f"# title: T\n1.1 Intro\n\nline one\nline two\n{PAGE_BREAK}\nnext page\n", "fallback")
    assert doc.title == "T"
    assert doc.pages == [["1.1 Intro", "line one line two"], ["next page"]]


def test_render_pdf_refuses_to_overflow_a_page():
    doc = parse_source("\n\n".join(["word " * 80] * 20), "big")
    with pytest.raises(ValueError, match="overflows"):
        render_pdf(doc)


def test_corpus_docs_build_with_stable_pages_and_sections():
    for key in ("docs/operations.txt", "docs/finance.txt"):
        doc = load_doc(key)
        assert 4 <= doc.page_count <= 6
        assert len(doc.chunks) >= 10
        assert all(c.section for c in doc.chunks)
    ops = load_doc("docs/operations.txt")
    little = next(c for c in ops.chunks if "Little's Law states" in c.text)
    assert (little.page_start, little.section.split(" > ")[-1]) == (1, "1.1 Little's Law")


# ---- end to end (mock) ----

def test_mock_eval_smoke_on_one_doc():
    cases, cfg = filter_docs(load_gold(DEFAULT_GOLD), load_quiz_config(DEFAULT_QUIZ), ["docs/finance.txt"])
    report = run_eval(MockProvider(), cases, cfg, k=6, meta={"provider": "mock"})
    m = report["metrics"]
    assert report["counts"]["cases"] == len(cases)
    assert m["citation_validity_rate"] >= 0.9  # mock quotes verbatim
    assert m["not_found_precision"] == 1.0  # the mock never declines a covered question here
    # BM25 + mock answer some off-topic questions that share a word ("capital", "year");
    # that is a known weakness the baseline records, so only sanity-check the range.
    assert 0.0 < m["not_found_recall"] <= 1.0
    assert m["retrieval_recall_at_k"] >= 0.9
    assert m["question_validity_rate"] == 1.0
    assert 0.0 < m["key_fact_recall"] < 1.0
    assert "citation_validity_rate" in format_table(report)


def test_cli_exits_nonzero_on_regression_against_baseline():
    perfect = {"metrics": {"not_found_recall": 1.0, "citation_validity_rate": 1.0, "key_fact_recall": 1.0}}
    with tempfile.TemporaryDirectory() as tmp:
        base, out = Path(tmp) / "base.json", Path(tmp) / "out.json"
        base.write_text(json.dumps(perfect))
        code = main(["--docs", "docs/finance.txt", "--baseline", str(base), "--out", str(out)])
        assert code == 1
        assert json.loads(out.read_text())["meta"]["provider"] == "mock"
        assert main(["--docs", "docs/finance.txt", "--baseline", str(out), "--fail-under-citation", "0.95"]) == 0
