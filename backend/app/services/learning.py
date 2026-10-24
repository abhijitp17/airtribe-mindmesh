"""Learning-loop use cases: tutor answers, quiz generation, answer grading.

These functions take plain data plus a Gateway and contain no web or
database code, so the whole loop is testable with the mock provider.
"""
from __future__ import annotations

import logging
import threading
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from typing import Sequence

from ..ai import prompts
from ..ai.gateway import BudgetExceeded, Gateway, ModelError, Request
from ..config import get_settings
from ..core import answerability
from ..core.assessment import (
    Grade,
    InvalidQuestion,
    QuestionSpec,
    dedupe,
    grade_mcq,
    normalize_rubric_grade,
    validate_question,
)
from ..core.citations import SourceRef, VerificationResult, verify
from ..core.embeddings import get_embedder
from ..core.graph_retrieval import GraphHints, defining_chunks, expand_query, promote
from ..core.hybrid import CANDIDATE_DEPTH, HybridHit, HybridRetriever
from ..core.hybrid import gate as hybrid_gate
from ..core.hybrid import is_covered, is_supported
from ..core.retrieval import BM25Retriever, Hit, Indexable, Retriever

log = logging.getLogger("mindmesh.learning")

TOP_K = 6
MIN_SCORE = 0.5  # BM25 floor below which we treat the query as not covered (= hybrid.BM25_FOUND_THRESHOLD)


@dataclass
class ChunkData:
    id: str
    text: str
    page_start: int
    page_end: int
    section: str
    document_id: str = ""


def retrieve(chunks: Sequence[ChunkData], query: str, k: int = TOP_K, hints: GraphHints | None = None,
             dense: dict[str, float] | None = None) -> list[SourceRef]:
    """Top-k sources for ``query``, or [] when the documents don't cover it.

    Hybrid BM25 + embedding retrieval fused with RRF (CONTRACTS §5) when an
    embedder is configured (``EMBEDDER=hash``, the default). With
    ``EMBEDDER=none`` it's v1's BM25 with the ``MIN_SCORE`` floor. The coverage
    gate is documented and calibrated in ``core.hybrid``.
    """
    if not chunks:
        return []
    by_id = {c.id: c for c in chunks}
    retriever = _retriever_for(chunks)
    search_query = expand_query(query, hints)  # P2: other names of concepts the question mentions
    wanted = defining_chunks(query, hints)
    depth = max(k, 20) if wanted else k
    if isinstance(retriever, HybridRetriever) and dense:
        # Coverage ("is this in the documents?") is decided as without dense retrieval, so a weak or
        # uncalibrated embedder can't turn a found question into not-found or the reverse. Dense
        # scores only re-rank, and join the gate once a threshold is calibrated for the model.
        threshold = get_settings().dense_found_threshold
        lexical = retriever.search(search_query, depth)
        deep = retriever.search(search_query, depth, dense=dense)
        covered = is_covered(lexical) or (threshold is not None and is_covered(deep, threshold))
        gated = [h for h in deep if is_supported(h, threshold)] if covered else []
    elif isinstance(retriever, HybridRetriever):
        deep: Sequence[Hit] = retriever.search(search_query, depth)
        gated = hybrid_gate(deep)
    else:
        deep = retriever.search(search_query, depth)
        gated = [h for h in deep if h.score >= MIN_SCORE]
    if wanted and gated:  # only when the documents cover the question at all
        by_hit = {h.id: h for h in deep}
        ids = promote([h.id for h in gated], [h.id for h in deep], wanted, k)
        hits = [by_hit[i] for i in ids]
    else:
        hits = list(gated)[:k]
    return [
        SourceRef(f"S{i}", h.id, by_id[h.id].text, by_id[h.id].page_start, by_id[h.id].page_end, by_id[h.id].section)
        for i, h in enumerate(hits, start=1)
    ]


# Fitted retrievers per corpus, so repeated questions over the same documents
# don't re-tokenise and refit IDF each time. 32 entries is enough for a few
# active users per worker. A 3k-chunk hybrid index is ~55 MB (mostly the
# inverted char-gram index), so the worst case is ~1.8 GB, and typical
# corpora are far smaller.
_RETRIEVER_CACHE_SIZE = 32
_retriever_cache: "OrderedDict[tuple, Retriever]" = OrderedDict()
_retriever_lock = threading.Lock()


def _corpus_key(chunks: Sequence[ChunkData], embedder_name: str) -> tuple:
    """(chunk ids, embedder name, content fingerprint).

    Chunk ids are database UUIDs, and re-ingestion writes new ones, so ids
    alone identify a corpus in production. The crc32 of the texts (~1 ms for
    3k chunks) also covers callers that reuse ids for different text, such
    as tests or ad-hoc ChunkData lists, so a stale index is never served.
    """
    fp = 0
    for c in chunks:
        fp = zlib.crc32(c.section.encode("utf-8"), zlib.crc32(c.text.encode("utf-8"), fp))
    return (tuple(c.id for c in chunks), embedder_name, fp)


def _retriever_for(chunks: Sequence[ChunkData]) -> Retriever:
    embedder = get_embedder()
    key = _corpus_key(chunks, embedder.name if embedder is not None else "bm25")
    with _retriever_lock:
        cached = _retriever_cache.get(key)
        if cached is not None:
            _retriever_cache.move_to_end(key)
            return cached
    docs = [Indexable(c.id, c.text, c.section) for c in chunks]
    built: Retriever = HybridRetriever(docs, embedder) if embedder is not None else BM25Retriever(docs)
    with _retriever_lock:
        _retriever_cache[key] = built
        _retriever_cache.move_to_end(key)
        while len(_retriever_cache) > _RETRIEVER_CACHE_SIZE:
            _retriever_cache.popitem(last=False)
    return built


def _require_answer(data: object) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("answer"), str):
        raise ValueError("tutor reply must be an object with an 'answer' string")
    return data


@dataclass
class TutorResult:
    answer: str
    status: str  # verified | partial | unverified | not_found | general
    citations: list[dict]
    retrieved: int


def ask_tutor(
    gw: Gateway,
    chunks: Sequence[ChunkData],
    question: str,
    level: str = "standard",
    history: list[tuple[str, str]] | None = None,
    allow_general: bool = False,
    hints: GraphHints | None = None,
    dense: dict[str, float] | None = None,
) -> TutorResult:
    sources = retrieve(chunks, question, hints=hints, dense=dense)
    if sources and not _is_answerable(gw, chunks, question, sources):
        sources = []  # CONTRACTS §8: same outcome as "not covered", without calling the tutor
    if not sources:
        if allow_general:
            return _general_answer(gw, question)
        return TutorResult(
            "I couldn't find anything about this in your selected documents. "
            "You can rephrase, select other documents, or ask for a clearly labelled general explanation.",
            "not_found", [], 0,
        )

    data = gw.complete_json(
        Request(
            task="tutor",
            system=prompts.TUTOR_SYSTEM,
            user=prompts.tutor_user(question, sources, level, history),
            tier="main",
            max_tokens=1500,
            context={"sources": sources, "question": question, "level": level},
        ),
        validate=_require_answer,
    )
    found = bool(data.get("found", True))
    claimed = data.get("citations") if isinstance(data.get("citations"), list) else []
    result: VerificationResult = verify(str(data.get("answer", "")), claimed, sources, found)
    if result.status == "not_found" and allow_general:
        return _general_answer(gw, question)
    if result.rejected:
        log.info("tutor rejected %d citation(s): %s", len(result.rejected), [r["reason"] for r in result.rejected])
    return TutorResult(
        prompts.strip_role_tags(result.answer),
        result.status,
        [
            {
                "label": c.label, "chunk_id": c.chunk_id, "quote": c.quote,
                "page_start": c.page_start, "page_end": c.page_end, "section": c.section,
            }
            for c in result.citations
        ],
        len(sources),
    )


ANSWERABLE_SOURCES = 3  # §8: the model check sees the top 3 sources


def _hit_signals(hit: Hit | None) -> dict[str, float]:
    """Raw bm25/cosine of a hit. BM25-only retrievers expose bm25 as ``score``."""
    if hit is None:
        return {"bm25": 0.0, "cosine": 0.0}
    if isinstance(hit, HybridHit):
        return {"bm25": hit.bm25, "cosine": hit.cosine}
    return {"bm25": hit.score, "cosine": 0.0}


def lexical_coverage(chunks: Sequence[ChunkData], question: str, sources: list[SourceRef]) -> str:
    """The no-model answerability verdict (CONTRACTS §8): confident | uncertain | not_found."""
    if not sources:
        return "not_found"
    hits = _retriever_for(chunks).search(question, CANDIDATE_DEPTH)
    by_id = {h.id: h for h in hits}
    verdict = answerability.lexical_verdict(question, sources, [_hit_signals(by_id.get(s.chunk_id)) for s in sources])
    return {"confident": "confident", "uncertain": "uncertain"}.get(verdict, "not_found")


def _is_answerable(gw: Gateway, chunks: Sequence[ChunkData], question: str, sources: list[SourceRef]) -> bool:
    """Answerability gate (CONTRACTS §8, ``core.answerability``).

    Lexical guard first. Only an "uncertain" verdict costs a fast-tier model
    call. If that reply is unusable even after the gateway's repair attempt,
    we keep the lexical verdict (``fallback_answerable``), which lets the
    question through. A broken model must not silently block real questions.
    ``BudgetExceeded`` and ``ModelError`` (provider down after retries) still
    propagate, so the router maps them to 429/503 like the tutor call.
    """
    # Signals for every source, including ones dense retrieval or graph hints moved up (cached index: cheap).
    hits = _retriever_for(chunks).search(question, CANDIDATE_DEPTH)
    by_id = {h.id: h for h in hits}
    meta = [_hit_signals(by_id.get(s.chunk_id)) for s in sources]
    verdict = answerability.lexical_verdict(question, sources, meta)
    log.info("answerability lexical verdict=%s", verdict)
    if verdict != "uncertain":
        return verdict == "confident"
    top = sources[:ANSWERABLE_SOURCES]
    try:
        data = gw.complete_json(
            Request(
                task="answerable",
                system=prompts.ANSWERABLE_SYSTEM,
                user=prompts.answerable_user(question, top),
                tier="fast",
                max_tokens=200,
                temperature=0.0,
                context={"sources": top, "question": question},
            ),
            validate=answerability.parse_answerable,
        )
    except (BudgetExceeded, ModelError):
        raise
    except Exception as exc:  # noqa: BLE001 - unparseable after repair: fall back, never block
        log.warning("answerable check unusable (%s); using lexical verdict", type(exc).__name__)
        return answerability.fallback_answerable(verdict)
    log.info("answerability model answerable=%s", data["answerable"])
    return data["answerable"]


def _general_answer(gw: Gateway, question: str) -> TutorResult:
    data = gw.complete_json(Request(
        task="general", system=prompts.GENERAL_SYSTEM, user=question, tier="main", max_tokens=1200,
        context={"question": question},
    ))
    return TutorResult(prompts.strip_role_tags(str(data.get("answer", ""))), "general", [], 0)


def _spread_sources(chunks: Sequence[ChunkData], focus: str | None, limit: int = 8) -> list[SourceRef]:
    """Pick source chunks for quiz generation: focused search, or an even spread."""
    if focus:
        found = retrieve(chunks, focus, k=limit)
        if found:
            return found
    substantive = [c for c in chunks if len(c.text) >= 200] or list(chunks)
    if not substantive:
        return []
    step = max(1, len(substantive) // limit)
    picked = substantive[::step][:limit]
    return [SourceRef(f"S{i}", c.id, c.text, c.page_start, c.page_end, c.section) for i, c in enumerate(picked, start=1)]


@dataclass
class GeneratedQuestion:
    spec: QuestionSpec
    source_chunk_ids: list[str]


def generate_quiz(
    gw: Gateway,
    chunks: Sequence[ChunkData],
    count: int = 5,
    difficulty: str = "medium",
    focus: str | None = None,
) -> list[GeneratedQuestion]:
    sources = _spread_sources(chunks, focus)
    if not sources:
        return []
    count = max(1, min(count, 15))
    n_applied = max(1, count // 4) if count >= 3 else 0  # PRD FR-044: at least one applied item
    n_short = max(1, count // 4) if count >= 4 else 0
    mix = {"mcq": count - n_applied - n_short, "short": n_short, "applied": n_applied}

    data = gw.complete_json(Request(
        task="quiz_generate",
        system=prompts.QUIZ_SYSTEM,
        user=prompts.quiz_user(sources, count, mix, difficulty, focus),
        tier="fast",
        max_tokens=4000,
        temperature=0.5,
        context={"sources": sources, "mix": mix, "difficulty": difficulty},
    ))
    raw_items = data.get("questions", []) if isinstance(data, dict) else []
    labels = {s.label for s in sources}
    label_to_chunk = {s.label: s.chunk_id for s in sources}
    specs: list[QuestionSpec] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            specs.append(validate_question(raw, labels))
        except InvalidQuestion as exc:
            log.info("dropped invalid generated question: %s", exc)
    specs = dedupe(specs)[:count]
    return [GeneratedQuestion(s, [label_to_chunk[l] for l in s.source_labels]) for s in specs]


def grade_answer(
    gw: Gateway,
    qtype: str,
    prompt: str,
    answer_key: str,
    rubric: list[dict],
    options: list[str],
    correct_index: int | None,
    explanation: str,
    sources: list[SourceRef],
    answer_text: str | None,
    selected_index: int | None,
) -> Grade:
    if qtype == "mcq":
        return grade_mcq(correct_index if correct_index is not None else -1, selected_index, options, explanation)
    if not answer_text or len(answer_text.strip()) < 2:
        return Grade("unassessed", 0.0, "No answer was submitted.")
    raw = gw.complete_json(Request(
        task="grade",
        system=prompts.GRADE_SYSTEM,
        user=prompts.grade_user(prompt, answer_key, rubric, sources, answer_text[:6000]),
        tier="main",
        max_tokens=1200,
        temperature=0.0,
        context={"answer": answer_text, "answer_key": answer_key, "rubric": rubric},
    ))
    return normalize_rubric_grade(raw if isinstance(raw, dict) else {}, rubric)
