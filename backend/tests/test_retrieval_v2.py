"""Retrieval v2 (hybrid BM25 + hashed embeddings, RRF) and the OCR fallback (WS E).

The corpus and query sets here are also the calibration data for
``core.hybrid.COSINE_FOUND_THRESHOLD`` / ``COSINE_SUPPORT_FLOOR``. If you
change the embedder or the gate, re-run ``test_gate_calibration_margins``.
"""
from __future__ import annotations

import builtins
import contextlib
import shutil
import time

import numpy as np
import pytest

from app.core import hybrid, ocr
from app.core.embeddings import HASH_DIM, HashingEmbedder, get_embedder
from app.core.hybrid import (
    COSINE_FOUND_THRESHOLD,
    COSINE_SUPPORT_FLOOR,
    RRF_K,
    HybridHit,
    HybridRetriever,
    gate,
    rrf_fuse,
)
from app.core.pdf_extract import (
    MIN_CHARS_PER_PAGE,
    PageText,
    apply_ocr,
    extract_pdf,
    format_page_list,
    merge_ocr,
    ocr_note,
)
from app.core.retrieval import BM25Retriever, Indexable
from app.services import learning
from app.services.learning import ChunkData, retrieve

from .conftest import make_pdf

# One to three sentences per chunk, across three technical domains, so that
# off-topic queries can't hide behind a single-topic corpus.
CORPUS: list[tuple[str, str, str]] = [
    ('little', "1.1 Little's Law",
     "Little's Law states that work in process equals throughput multiplied by cycle time. Written as WIP = TH x CT, it holds for any stable line. A line with 120 jobs in process and throughput of 40 jobs per day has an average cycle time of three days."),
    ('variability', '1.2 Variability',
     'Variability degrades the performance of a production system. Higher variability in arrivals or processing times increases queue time. The coefficient of variation is the standard deviation divided by the mean.'),
    ('buffers', '1.3 Buffers',
     'Buffers against variability take three forms: inventory, capacity, and time. A system that does not buffer with inventory must buffer with capacity or time.'),
    ('bottleneck', '1.4 Bottlenecks',
     'The bottleneck is the workstation with the highest utilization. It determines the maximum throughput of the line; improving non-bottleneck stations does not increase output.'),
    ('kanban', '1.5 Pull systems',
     'Kanban is a pull system in which cards authorize production. Limiting WIP with cards reduces congestion and makes cycle times predictable.'),
    ('utilization', '1.6 Utilization',
     "Utilization is the fraction of time a resource is busy. As utilization approaches one, queueing delay grows without bound according to Kingman's formula."),
    ('eoq', '2.1 Economic order quantity',
     'The economic order quantity balances setup cost against inventory holding cost. Ordering in larger lots lowers setups but raises holding cost.'),
    ('safety', '2.2 Safety stock',
     'Safety stock protects against demand uncertainty during the replenishment lead time. Higher service levels require more safety stock.'),
    ('wc', '3.1 Working capital',
     "Working capital is current assets minus current liabilities. It measures the liquidity available to fund a firm's operational needs such as inventory and receivables."),
    ('ccc', '3.2 Cash conversion cycle',
     'The cash conversion cycle measures how many days cash is tied up in inventory and receivables before being collected from customers, net of payables days.'),
    ('npv', '3.3 Net present value',
     'Net present value discounts future cash flows at the cost of capital and subtracts the initial investment. Accept projects with positive NPV.'),
    ('depr', '3.4 Depreciation',
     'Depreciation allocates the cost of a tangible asset over its useful life. Straight-line depreciation charges an equal amount every year.'),
    ('roe', '3.5 Return on equity',
     "Return on equity is net income divided by shareholders' equity. The DuPont identity splits it into margin, asset turnover and leverage."),
    ('overfit', '4.1 Overfitting',
     'Overfitting happens when a model memorizes training data and generalizes poorly to unseen examples. Regularization and cross-validation reduce it.'),
    ('gd', '4.2 Gradient descent',
     'Gradient descent minimizes a loss function by repeatedly stepping in the direction of the negative gradient, scaled by the learning rate.'),
    ('bias', '4.3 Bias and variance',
     'The bias-variance tradeoff: simple models underfit with high bias, while flexible models have high variance across training sets.'),
    ('precision', '4.4 Precision and recall',
     'Precision is the fraction of predicted positives that are correct; recall is the fraction of actual positives that are found.'),
    ('regul', '4.5 Regularization',
     'L2 regularization penalizes large weights, shrinking coefficients toward zero and improving generalization on held-out data.'),
    ('forecast', '5.1 Forecasting',
     'Exponential smoothing forecasts demand as a weighted average of past observations, with weights decaying geometrically into the past.'),
    ('quality', '5.2 Statistical process control',
     'Control charts monitor a process over time and signal when measurements fall outside the control limits, indicating special-cause variation.'),
]

# Paraphrases: the query wording differs from the chunk wording.
PARAPHRASE: list[tuple[str, str]] = [
    ("how long do jobs wait on average", "little"),
    ("money tied up in day-to-day operations", "wc"),
    ("which machine limits the output of the whole line", "bottleneck"),
    ("why do queues explode when machines are almost always busy", "utilization"),
    ("model memorising its training examples", "overfit"),
    ("protecting against uncertain customer demand", "safety"),
    ("spreading an asset's cost across the years it is used", "depr"),
    ("how quickly does a company turn its stock into cash", "ccc"),
    ("operational liquidity of the firm", "wc"),
]

# No exact stemmed-term overlap with the gold chunk (BM25 is blind to these):
# British spelling, typos / OCR noise, and morphology the stemmer misses.
VARIANTS: list[tuple[str, str]] = [
    ("what is utilisation", "utilization"),
    ("throughpt and cyle tme", "little"),
    ("generalisation", "regul"),
]

OFF_TOPIC: list[str] = [
    "Who won the 1998 football world cup?",
    "Name the largest cities of Europe",
    "How do I bake sourdough bread at home?",
    "recipe for chocolate chip cookies",
    "Which country has the largest population?",
    "what will the weather be like tomorrow in Paris",
    "best hiking trails near Denver",
    "Explain the plot of Hamlet and the motivations of its main characters",
    "Who painted the Mona Lisa?",
    "how to change a flat tyre on a bicycle",
    "how to make a vegetarian lasagna",
    "Best restaurants in Rome for pasta",
    "symptoms of the common cold versus influenza",
    "When was the Eiffel Tower constructed?",
    "rules of chess castling",
    "Which planets have rings?",
    "How do I renew my passport?",
    "who wrote pride and prejudice",
    "translate good morning into Japanese",
    "list of national parks in California",
]

# Off-topic queries that share one ordinary word with a chunk: "capital"
# (working capital), "lead" (lead time), "year", "training", "form", "high" (higher service levels). v1's BM25 floor already accepts these, and the v2
# gate (bm25 >= MIN_SCORE OR cosine >= threshold) is by construction a
# superset of v1. So the requirement is that v2 makes the same query-level
# decision as v1, adding no new false positives, and that they're rejected
# over a corpus without the colliding chunks.
HOMONYMS: list[str] = [
    "What is the capital of Australia?",
    "What is the capital city of France?",
    "Who is the lead singer of Coldplay?",
    "What year did the Berlin wall fall?",
    "Tips for training a puppy to sit and stay",
    "How do volcanoes form and why do they erupt?",
    "what is the boiling point of water at high altitude",
]
CAPITALS = HOMONYMS[:2]
FINANCE_IDS = {"wc", "ccc", "npv", "depr", "roe"}


def _docs() -> list[Indexable]:
    return [Indexable(i, t, s) for i, s, t in CORPUS]


def _chunks() -> list[ChunkData]:
    return [ChunkData(i, t, n, n, s) for n, (i, s, t) in enumerate(CORPUS, start=1)]


def _recall_at(retriever, queries: list[tuple[str, str]], k: int) -> int:
    return sum(gold in [h.id for h in retriever.search(q, k)] for q, gold in queries)


# ---------- Embedder ----------

def test_embedder_is_deterministic_and_normalised():
    texts = [t for _, _, t in CORPUS]
    a = HashingEmbedder().fit(texts)
    b = HashingEmbedder().fit(texts)
    va, vb = a.embed(texts[:3]), b.embed(texts[:3])
    assert va.shape == (3, HASH_DIM) and va.dtype == np.float32
    assert np.array_equal(va, vb)  # stable hash (crc32), not the salted Python hash()
    assert np.allclose(np.linalg.norm(va, axis=1), 1.0, atol=1e-5)
    sparse = a.embed_sparse(texts[:3])
    assert np.allclose(sparse.to_dense(), va)
    # Empty or stopword-only input gives a zero vector, not NaN.
    z = a.embed(["", "the of and"])
    assert np.all(z == 0) and not np.isnan(z).any()


def test_embedder_requires_fit_and_cosine_is_bounded():
    with pytest.raises(RuntimeError, match="fit"):
        HashingEmbedder().embed(["x"])
    e = HashingEmbedder().fit([t for _, _, t in CORPUS])
    v = e.embed(["working capital liquidity", "working capital liquidity", "gradient descent"])
    assert abs(float(v[0] @ v[1]) - 1.0) < 1e-5
    assert -1.0 <= float(v[0] @ v[2]) < 0.2


def test_char_ngrams_match_spelling_variants():
    e = HashingEmbedder().fit([t for _, _, t in CORPUS])
    v = e.embed(["utilization", "utilisation", "sourdough"])
    # Single words: only the char family (weight 0.40) can match, so the ceiling is 0.40.
    assert float(v[0] @ v[1]) > 0.15  # shares <uti, uti, til, ... ion>
    assert float(v[0] @ v[2]) < 0.05


def test_get_embedder_reads_setting():
    assert isinstance(get_embedder("hash"), HashingEmbedder)
    assert get_embedder("none") is None
    assert get_embedder("no-such-model") is None  # logged, falls back to lexical


# ---------- RRF ----------

def test_rrf_math():
    fused = rrf_fuse([["a", "b", "c"], ["b", "d"]])
    assert RRF_K == 60
    assert fused["a"] == pytest_approx(1 / 61)
    assert fused["b"] == pytest_approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest_approx(1 / 63)
    assert fused["d"] == pytest_approx(1 / 62)
    # Agreement across lists beats a single first place.
    assert max(fused, key=fused.get) == "b"
    assert rrf_fuse([]) == {} and rrf_fuse([[], []]) == {}


def pytest_approx(x: float, tol: float = 1e-12):
    class _A:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, float) and abs(other - x) < tol
    return _A()


def test_hybrid_hits_expose_raw_signals():
    r = HybridRetriever(_docs(), HashingEmbedder())
    hits = r.search("What is Little's Law?", 3)
    assert isinstance(hits[0], HybridHit) and hits[0].id == "little"
    top = hits[0]
    assert top.bm25 > 0.5 and top.cosine > COSINE_FOUND_THRESHOLD
    assert top.bm25_rank == 1 and top.cosine_rank == 1
    assert top.score == pytest_approx(2 / (RRF_K + 1))
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert HybridRetriever([], HashingEmbedder()).search("x") == []
    assert r.search("   ") == []


# ---------- Paraphrase recall ----------

def test_paraphrase_recall_hybrid_beats_bm25():
    bm25, hyb = BM25Retriever(_docs()), HybridRetriever(_docs(), HashingEmbedder())
    b3, h3 = _recall_at(bm25, PARAPHRASE, 3), _recall_at(hyb, PARAPHRASE, 3)
    assert h3 >= b3
    assert h3 > b3, f"hybrid recall@3 {h3} should beat BM25 {b3} on paraphrases"
    v3_b, v3_h = _recall_at(bm25, VARIANTS, 3), _recall_at(hyb, VARIANTS, 3)
    assert v3_b == 0 and v3_h == len(VARIANTS)
    # Lexical queries don't regress.
    lexical = [("What is Little's Law?", "little"), ("net present value", "npv"), ("kanban cards", "kanban")]
    assert _recall_at(hyb, lexical, 1) == len(lexical)


def test_named_paraphrases_through_service():
    srcs = retrieve(_chunks(), "how long do jobs wait on average", k=3)
    assert "little" in [s.chunk_id for s in srcs]
    srcs = retrieve(_chunks(), "money tied up in day-to-day operations", k=3)
    assert "wc" in [s.chunk_id for s in srcs]
    # BM25 alone misses working capital here; the embedder adds it.
    assert "wc" not in [h.id for h in BM25Retriever(_docs()).search("money tied up in day-to-day operations", 3)]
    srcs = retrieve(_chunks(), "what is utilisation", k=3)
    assert srcs and srcs[0].chunk_id == "utilization"


# ---------- Not-found gate ----------

def test_gate_rejects_off_topic_queries():
    for q in OFF_TOPIC:
        assert retrieve(_chunks(), q) == [], q
    no_finance = [c for c in _chunks() if c.id not in FINANCE_IDS]
    for q in CAPITALS:
        assert retrieve(no_finance, q) == [], q


def test_homonyms_match_v1_behaviour():
    """Known limitation, documented in core.hybrid: lexical homonyms pass the
    BM25 branch in v1 and v2 alike. v2 adds no new false positives. The tutor's
    found=false answer and citation verification are the next line of defence."""
    bm25 = BM25Retriever(_docs())
    for q in OFF_TOPIC + HOMONYMS:
        v1_found = any(h.score >= learning.MIN_SCORE for h in bm25.search(q))
        assert bool(retrieve(_chunks(), q)) == v1_found, q


def test_gate_calibration_margins():
    """The documented calibration in core.hybrid, as an executable check."""
    r = HybridRetriever(_docs(), HashingEmbedder())
    ids = [d.id for d in _docs()]
    noise = [h.cosine for q in OFF_TOPIC + HOMONYMS for h in r.search(q, 50) if h.bm25 < 0.5]
    assert max(noise) < COSINE_FOUND_THRESHOLD
    assert float(np.percentile(noise, 95)) < COSINE_SUPPORT_FLOOR
    for q, gold in VARIANTS:
        assert float(r.cosines(q)[ids.index(gold)]) >= COSINE_FOUND_THRESHOLD, q


def test_gate_filters_noise_hits_but_keeps_evidence():
    strong = HybridHit("a", 0.03, bm25=4.0, cosine=0.3)
    embed_only = HybridHit("b", 0.02, bm25=0.0, cosine=0.05)
    noise = HybridHit("c", 0.01, bm25=0.0, cosine=0.01)
    assert [h.id for h in gate([strong, embed_only, noise])] == ["a", "b"]
    assert gate([embed_only, noise]) == []  # nothing clears a "found" threshold


def test_bm25_only_mode_keeps_v1_behaviour():
    hits = BM25Retriever(_docs()).search("Little's Law", 6)
    assert gate(hits) == [h for h in hits if h.score >= learning.MIN_SCORE]


def test_retriever_cache_reuses_and_invalidates():
    learning._retriever_cache.clear()
    chunks = _chunks()
    retrieve(chunks, "little's law")
    first = learning._retriever_for(chunks)
    retrieve(chunks, "working capital")
    assert learning._retriever_for(chunks) is first and len(learning._retriever_cache) == 1
    edited = list(chunks)
    edited[0] = ChunkData("little", "Totally different text about sourdough.", 1, 1, "x")
    assert learning._retriever_for(edited) is not first  # same ids, new text -> rebuilt
    for i in range(learning._RETRIEVER_CACHE_SIZE + 3):
        learning._retriever_for(chunks[: (i % len(chunks)) + 1] + [ChunkData(f"z{i}", "pad", 1, 1, "")])
    assert len(learning._retriever_cache) <= learning._RETRIEVER_CACHE_SIZE


def test_hybrid_latency_3000_chunks():
    rng = np.random.default_rng(7)
    vocab = sorted({w for _, _, t in CORPUS for w in t.split()}) + [f"term{i}" for i in range(4000)]
    chunks = [
        ChunkData(f"s{i}", " ".join(rng.choice(vocab, 180)), i // 3 + 1, i // 3 + 1, f"Section {i // 20}")
        for i in range(3000)
    ]
    t0 = time.perf_counter()
    retrieve(chunks, "how long do jobs wait")
    build = time.perf_counter() - t0
    t0 = time.perf_counter()
    for q in ["cycle time", "working capital liquidity", "football world cup", "utilisation"]:
        retrieve(chunks, q)
    warm = (time.perf_counter() - t0) / 4
    print(f"[latency] 3000 chunks: build+first query {build * 1000:.0f} ms, cached query {warm * 1000:.1f} ms")
    # Loose CI bounds (measured ~2.6 s / ~10 ms on the dev sandbox).
    assert build < 15.0 and warm < 0.25


# ---------- OCR ----------

def test_ocr_off_is_noop():
    assert ocr.ocr_pages(b"%PDF-not-even-parsed", [1, 2, 3], engine="off") == {}


def test_ocr_never_raises_on_bad_input():
    assert ocr.ocr_pages(b"garbage", [1], engine="tesseract") == {}
    assert ocr.ocr_pages(b"garbage", [], engine="tesseract") == {}
    assert ocr.ocr_pages(b"", [1], engine="vision") == {}


@contextlib.contextmanager
def _without_module(name: str):
    import sys

    real_import = builtins.__import__
    saved = sys.modules.pop(name, None)

    def fake_import(mod, *a, **k):
        if mod == name or mod.startswith(name + "."):
            raise ImportError(f"No module named {name!r}")
        return real_import(mod, *a, **k)

    builtins.__import__ = fake_import
    try:
        yield
    finally:
        builtins.__import__ = real_import
        if saved is not None:
            sys.modules[name] = saved


def test_ocr_graceful_when_pytesseract_missing():
    pdf = make_pdf([[""], [""]])
    with _without_module("pytesseract"):
        assert ocr._tesseract_engine() is None
        assert ocr.ocr_pages(pdf, [1, 2], engine="tesseract") == {}


def test_ocr_respects_page_cap_and_budget():
    pdf = make_pdf([["page one text"], ["page two text"], ["page three text"]])
    calls: list[int] = []

    def fake_engine(image) -> str:
        calls.append(1)
        return "recognised text " * 10

    real = ocr._engine_for
    ocr._engine_for = lambda kind: fake_engine  # type: ignore[assignment]
    try:
        out = ocr.ocr_pages(pdf, [3, 1, 2, 99], engine="tesseract", max_pages=2)
        assert sorted(out) == [1, 2] and len(calls) == 2  # capped, in page order
        calls.clear()
        assert ocr.ocr_pages(pdf, [1, 2, 3], engine="tesseract", time_budget_s=0.0) == {}
        assert calls == []
    finally:
        ocr._engine_for = real  # type: ignore[assignment]


def test_ocr_tesseract_end_to_end_if_installed():
    """Runs only where pytesseract and the tesseract binary exist (e.g. the Docker image)."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return
    if shutil.which("tesseract") is None:
        return
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    import io

    # Draw text, then rasterise the page into an image-only PDF (a "scan").
    import pypdfium2 as pdfium

    src = make_pdf([["Little's Law relates work in process, throughput and cycle time.",
                     "Variability increases queue time in every production system."]])
    img = pdfium.PdfDocument(src)[0].render(scale=2).to_pil()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    from reportlab.lib.utils import ImageReader

    c.drawImage(ImageReader(img), 0, 0, *letter)
    c.showPage()
    c.save()
    scanned = buf.getvalue()
    r = extract_pdf(scanned)
    assert r.low_text_pages == [1] and r.needs_attention
    out = ocr.ocr_pages(scanned, r.low_text_pages, engine="tesseract")
    assert "throughput" in out.get(1, "").lower()
    merged, applied = apply_ocr(r, out)
    assert applied == [1] and not merged.needs_attention


# ---------- Ingestion OCR merge ----------

def _page(n: int, text: str) -> PageText:
    s = text.strip()
    return PageText(n, text, len(s), len(s) < MIN_CHARS_PER_PAGE)


GOOD = "This page has a perfectly fine text layer with enough characters to pass the bar. " * 2
OCR_TEXT = "Recovered by OCR: Little's Law states WIP equals throughput times cycle time, always."


def test_merge_ocr_replaces_only_low_text_pages():
    pages = [_page(1, GOOD), _page(2, ""), _page(3, "x"), _page(4, "")]
    ocr_map = {1: "SHOULD NOT REPLACE GOOD TEXT LAYER " * 5, 2: OCR_TEXT, 3: "noise", 9: OCR_TEXT}
    merged, applied = merge_ocr(pages, ocr_map)
    assert applied == [2]
    assert merged[0].text == GOOD  # good page untouched
    assert merged[1].text == OCR_TEXT and not merged[1].low_text
    assert merged[1].char_count == len(OCR_TEXT.strip())
    assert merged[2].low_text and merged[2].text == "x"  # OCR too short: kept and still flagged
    assert merged[3].low_text  # nothing from OCR
    assert pages[1].text == ""  # pure: input not mutated
    again, applied2 = merge_ocr(merged, ocr_map)  # idempotent
    assert applied2 == [] and [p.text for p in again] == [p.text for p in merged]


def test_apply_ocr_recomputes_attention_and_warnings():
    r = extract_pdf(make_pdf([[""], [""], ["short"]]))
    assert r.needs_attention and any("scanned" in w for w in r.warnings)
    merged, applied = apply_ocr(r, {1: OCR_TEXT, 2: OCR_TEXT, 3: OCR_TEXT})
    assert applied == [1, 2, 3] and not merged.needs_attention
    assert not any("little or no text" in w for w in merged.warnings)
    partial, applied = apply_ocr(r, {1: OCR_TEXT})
    assert applied == [1] and partial.low_text_pages == [2, 3] and partial.needs_attention
    assert any("2 of 3 pages" in w and "OCR could not recover" in w for w in partial.warnings)
    unchanged, applied = apply_ocr(r, {})
    assert applied == [] and unchanged.warnings == r.warnings


def test_ocr_status_note():
    assert format_page_list([1, 2, 3, 7, 9, 10]) == "1-3, 7, 9-10"
    assert ocr_note([4, 2, 3]) == "OCR applied to pages 2-4."
    assert ocr_note([]) is None
