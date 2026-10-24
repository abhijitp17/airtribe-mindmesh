from datetime import datetime, timedelta, timezone

import pytest

from app.core.assessment import (
    InvalidQuestion,
    dedupe,
    grade_mcq,
    normalize_rubric_grade,
    validate_question,
)
from app.core.chunking import chunk_pages, heading_level
from app.core.citations import SourceRef, quote_support, verify
from app.core.jsonutil import JSONExtractionError, extract_json
from app.core.mastery import AttemptEvidence, estimate
from app.core.pdf_extract import PdfExtractionError, extract_pdf
from app.core.retrieval import BM25Retriever, Indexable

from .conftest import make_pdf


# ---------- PDF extraction ----------

def test_extract_pages_are_one_based(sample_pdf):
    r = extract_pdf(sample_pdf)
    assert r.page_count == 2
    assert [p.page_number for p in r.pages] == [1, 2]
    assert "Little's Law" in r.pages[0].text
    assert "Variability" in r.pages[1].text
    assert not r.needs_attention
    assert r.title == "Factory Physics Sample"


def test_rejects_non_pdf():
    with pytest.raises(PdfExtractionError):
        extract_pdf(b"hello world")


def test_flags_blank_pages_as_needing_attention():
    r = extract_pdf(make_pdf([[""], [""], ["short"]]))
    assert r.needs_attention
    assert r.low_text_pages == [1, 2, 3]
    assert any("scanned" in w for w in r.warnings)


def test_page_limit():
    with pytest.raises(PdfExtractionError, match="limit"):
        extract_pdf(make_pdf([["a"], ["b"], ["c"]]), max_pages=2)


# ---------- Chunking ----------

def test_heading_detection():
    assert heading_level("CHAPTER 1 FLOW BASICS") == 1
    assert heading_level("1.1 Little's Law") == 2
    assert heading_level("2.3.1 Queue Discipline") == 3
    assert heading_level("This is a normal sentence that ends with a period.") is None
    assert heading_level("") is None


def test_chunks_keep_page_anchors_and_sections(sample_pdf):
    chunks = chunk_pages(extract_pdf(sample_pdf).pages)
    assert chunks, "expected chunks"
    little = next(c for c in chunks if "work in process equals" in c.text)
    assert little.page_start == 1
    assert little.section_path[-1] == "1.1 Little's Law"
    assert little.section_path[0] == "CHAPTER 1 FLOW BASICS"
    var = next(c for c in chunks if "coefficient of variation" in c.text)
    assert var.page_start == 2
    assert var.section_label.endswith("1.2 Variability")
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_long_text_is_split_without_losing_content():
    from app.core.pdf_extract import PageText

    sentence = "Throughput is the average output of a production process per unit time. "
    text = sentence * 80
    chunks = chunk_pages([PageText(1, text, len(text), False)])
    assert len(chunks) > 1
    assert all(len(c.text) <= 2000 for c in chunks)
    assert sum(c.text.count("Throughput") for c in chunks) == 80


# ---------- Retrieval ----------

def test_bm25_ranks_relevant_chunk_first():
    docs = [
        Indexable("a", "Variability increases queue time and cycle time."),
        Indexable("b", "Little's Law relates WIP, throughput, and cycle time."),
        Indexable("c", "Inventory buffers protect against demand uncertainty."),
    ]
    hits = BM25Retriever(docs).search("What is Little's Law?")
    assert hits[0].id == "b"
    assert BM25Retriever(docs).search("the of and") == []
    assert BM25Retriever([]).search("anything") == []


def test_bm25_stemming_matches_plurals():
    docs = [Indexable("x", "A buffer absorbs variability."), Indexable("y", "Unrelated text here.")]
    assert BM25Retriever(docs).search("buffers")[0].id == "x"


# ---------- Citations ----------

SRC = [
    SourceRef("S1", "c1", "Little's Law states that work in process equals throughput multiplied by cycle time.", 1, 1, "1.1"),
    SourceRef("S2", "c2", "Variability degrades the performance of a production system.", 2, 2, "1.2"),
]


def test_quote_support_tolerates_whitespace_and_hyphenation():
    assert quote_support("work in   process equals through-\nput multiplied", "work in process equals throughput multiplied by") > 0.9
    assert quote_support("completely unrelated claim about marketing", SRC[0].text) < 0.6


def test_verify_accepts_real_quotes():
    r = verify(
        "WIP equals throughput times cycle time [S1].",
        [{"source": "S1", "quote": "work in process equals throughput multiplied by cycle time"}],
        SRC,
        found=True,
    )
    assert r.status == "verified"
    assert r.citations[0].page_start == 1
    assert "[S1]" in r.answer


def test_verify_rejects_fabricated_quote_and_unknown_source():
    r = verify(
        "Claim one [S1]. Claim two [S2]. Claim three [S9].",
        [
            {"source": "S1", "quote": "work in process equals throughput multiplied by cycle time"},
            {"source": "S2", "quote": "variability always improves performance dramatically"},
            {"source": "S9", "quote": "a source that was never retrieved"},
        ],
        SRC,
        found=True,
    )
    assert r.status == "partial"
    assert [c.label for c in r.citations] == ["S1"]
    assert "[S2]" not in r.answer and "[S9]" not in r.answer
    assert {x["source"] for x in r.rejected} == {"S2", "S9"}


def test_verify_not_found():
    r = verify("The documents do not cover this [S1].", [], SRC, found=False)
    assert r.status == "not_found"
    assert r.citations == []
    assert "[S1]" not in r.answer


def test_verify_all_rejected_is_unverified():
    r = verify("Answer [S1].", [{"source": "S1", "quote": "too short"}], SRC, found=True)
    assert r.status == "unverified"


# ---------- Assessment ----------

MCQ = {
    "type": "mcq",
    "prompt": "According to Little's Law, WIP equals what?",
    "options": ["TH x CT", "TH / CT", "CT / TH", "TH + CT"],
    "correct_index": 0,
    "concept": "Little's Law",
    "difficulty": "easy",
    "explanation": "WIP = TH x CT.",
    "sources": ["S1"],
}


def test_validate_mcq_ok():
    q = validate_question(MCQ, {"S1"})
    assert q.answer_key == "TH x CT"


@pytest.mark.parametrize(
    "patch",
    [
        {"type": "essay"},
        {"options": ["a", "b"]},
        {"options": ["a", "a", "b"]},
        {"correct_index": 7},
        {"correct_index": True},
        {"sources": ["S99"]},
        {"prompt": "short"},
    ],
)
def test_validate_mcq_rejects_bad(patch):
    with pytest.raises(InvalidQuestion):
        validate_question({**MCQ, **patch}, {"S1"})


def test_validate_short_requires_rubric():
    raw = {"type": "short", "prompt": "Explain Little's Law in your own words.", "answer_key": "WIP = TH x CT", "sources": ["S1"]}
    with pytest.raises(InvalidQuestion):
        validate_question(raw, {"S1"})
    q = validate_question({**raw, "rubric": ["Names WIP, TH, CT", {"criterion": "States relationship", "points": 2}]}, {"S1"})
    assert [r.points for r in q.rubric] == [1, 2]


def test_dedupe():
    a = validate_question(MCQ, {"S1"})
    b = validate_question({**MCQ, "prompt": "According to Little's Law, WIP equals what value?"}, {"S1"})
    c = validate_question({**MCQ, "prompt": "Which buffers protect against variability?"}, {"S1"})
    assert len(dedupe([a, b, c])) == 2


def test_grade_mcq():
    assert grade_mcq(0, 0, ["a", "b", "c"], "why").verdict == "correct"
    g = grade_mcq(0, 2, ["a", "b", "c"], "why")
    assert g.verdict == "incorrect" and "a" in g.feedback
    assert grade_mcq(0, None, ["a", "b", "c"], "").verdict == "unassessed"


def test_rubric_score_is_recomputed_in_code():
    rubric = [{"criterion": "Defines WIP", "points": 1}, {"criterion": "States formula", "points": 2}, {"criterion": "Gives example", "points": 1}]
    raw = {
        "score": 1.0,  # model claims perfect; criteria disagree
        "feedback": "ok",
        "criteria": [
            {"criterion": "defines wip", "status": "met"},
            {"criterion": "States formula", "status": "partial"},
            {"criterion": "Gives example", "status": "bogus"},
        ],
    }
    g = normalize_rubric_grade(raw, rubric)
    assert g.score == 0.5
    assert g.verdict == "partial"
    assert g.missing == ["States formula", "Gives example"]


def test_rubric_without_criteria_is_unassessed():
    g = normalize_rubric_grade({"feedback": "?"}, [{"criterion": "x", "points": 1}])
    assert g.verdict == "unassessed"


# ---------- Mastery ----------

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def test_mastery_unverified_with_little_evidence():
    m = estimate("Little's Law", [AttemptEvidence(1.0, "mcq", "easy", NOW)], now=NOW)
    assert m.level == "unverified"
    assert "Only 1 answer so far" in m.explanation
    assert "Answer 2 more and we'll rate this" in m.explanation


def test_mastery_strong_and_weak():
    good = [AttemptEvidence(1.0, t, "medium", NOW) for t in ("mcq", "short", "applied")]
    assert estimate("x", good, now=NOW).level == "strong"
    bad = [AttemptEvidence(0.0, "mcq", "medium", NOW)] * 3
    m = estimate("x", bad, now=NOW)
    assert m.level == "weak" and m.due_for_review


def test_mastery_applied_weighs_more_than_recall():
    a = [AttemptEvidence(1.0, "mcq", "medium", NOW), AttemptEvidence(0.0, "applied", "medium", NOW)]
    assert estimate("x", a, now=NOW).estimate < 0.5


def test_mastery_review_due_after_time():
    old = NOW - timedelta(days=30)
    m = estimate("x", [AttemptEvidence(1.0, "short", "medium", old)] * 3, now=NOW)
    assert m.due_for_review
    assert "Last practised 30 days ago." in m.explanation
    assert m.explanation.startswith("You got 3 of 3 right")


def test_mastery_empty():
    assert estimate("x", [], now=NOW).level == "unverified"


# ---------- JSON ----------

def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Here you go:\n```json\n{"a": [1,2]}\n```') == {"a": [1, 2]}
    assert extract_json('noise {"a": "x}y"} trailing') == {"a": "x}y"}
    with pytest.raises(JSONExtractionError):
        extract_json("no json")
