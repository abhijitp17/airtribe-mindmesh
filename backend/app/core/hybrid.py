"""Hybrid retrieval: BM25 + embedding cosine, fused with Reciprocal Rank Fusion.

Why RRF (Cormack, Clarke & Büttcher, SIGIR 2009): BM25 scores are unbounded
and corpus-dependent, while cosine scores sit in [-1, 1] with an
embedder-specific scale. Mixing the raw scores linearly needs per-corpus
normalisation that breaks easily. RRF uses ranks only:

    rrf(d) = sum over lists L containing d of 1 / (RRF_K + rank_L(d))

RRF_K = 60 is the constant from the paper. It's widely used as a default and
damps the gap between rank 1 and rank 2, so that agreement between two lists
beats a single top rank.

The "not covered" gate (two levels)
-----------------------------------
RRF scores only order documents; they say nothing about whether the corpus
covers the query (every non-empty list has a rank-1 document). So each
``HybridHit`` keeps both raw signals, and the gate uses those:

1. Query level (``is_covered``). The query is covered iff some top-k fused hit has
       bm25 >= BM25_FOUND_THRESHOLD  OR  cosine >= COSINE_FOUND_THRESHOLD.
   ``BM25_FOUND_THRESHOLD`` is v1's ``learning.MIN_SCORE`` (0.5). So every
   query v1 answered is still answered, and the cosine branch only adds recall
   for paraphrases, spelling variants and OCR typos with no exact-term match.
2. Hit level (``is_supported``). When the query is covered, the top-k fused hits
   are returned, minus those with no evidence at all: no shared stemmed term
   (bm25 == 0) and cosine below the noise floor. This keeps a paraphrase's
   gold chunk that only the embedder found (e.g. "money tied up in day-to-day
   operations" -> working capital: bm25 0, cosine ~0.05) while dropping
   filler sources.

Calibration (HashingEmbedder "hash-v1"; reproduced by tests/test_retrieval_v2.py)
on a 20-chunk technical corpus (operations, finance, ML, 1-3 sentences each)
and 27 off-topic queries (sport, geography, cooking, culture, travel):
    off-topic cosine over chunks without a lexical match: max 0.044, p95 0.021
    zero-lexical-overlap true matches ("utilisation", "throughpt and cyle tme",
    "generalisation", ...): 0.085-0.096 for the gold chunk
    lexical paraphrases: 0.05-0.35 (most pass via BM25 anyway)
COSINE_FOUND_THRESHOLD = 0.07 sits between the off-topic max and the
true-match min (midpoint 0.065, rounded up for precision). COSINE_SUPPORT_FLOOR
= 0.025 is just above the off-topic p95.

Known limitations: (a) Off-topic queries that share an ordinary word with a
chunk ("capital of France" vs "working capital") pass the BM25 branch, exactly
as in v1. The tests assert v2 adds no new false positives. Downstream, the
tutor's found=false and citation verification still apply. (b) Cosine falls with chunk length (more features dilute the
norm). For 5-paragraph chunks a zero-overlap variant scores only ~0.03, so for
long chunks the cosine branch mostly helps ranking (via RRF), not the gate.
A learned embedder (see embeddings.py) is needed to go beyond this. It must
come with its own calibration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .embeddings import Embedder, SparseEmbedder, SparseRows
from .retrieval import BM25Retriever, Hit, Indexable

RRF_K = 60  # Cormack et al. 2009. See the module docstring.

# Candidates taken from each ranker before fusion. Answers use at most ~8
# sources, so 50 leaves plenty of room for a document ranked low by one
# signal but high by the other to surface, while keeping the fusion cheap.
CANDIDATE_DEPTH = 50

# Same value as services.learning.MIN_SCORE (v1 behaviour, kept unchanged).
BM25_FOUND_THRESHOLD = 0.5

# Calibrated for HashingEmbedder ("hash-v1"). See "Calibration" in the module
# docstring. Re-calibrate for any other embedder (cosine scales differ a lot).
COSINE_FOUND_THRESHOLD = 0.07
# Hit-level noise floor: just above the p95 off-topic cosine (0.021).
COSINE_SUPPORT_FLOOR = 0.025


@dataclass(frozen=True)
class HybridHit(Hit):
    """``score`` is the RRF score, used for ranking only and not comparable
    across queries. ``bm25`` and ``cosine`` are the raw signals behind the
    coverage gate. They're 0.0 when the hit wasn't in that ranker's candidates."""

    bm25: float = 0.0
    cosine: float = 0.0
    bm25_rank: int | None = None  # 1-based, None if not a BM25 candidate
    cosine_rank: int | None = None
    dense: float = 0.0  # learned-embedding cosine (core.dense), 0.0 when dense retrieval is off
    dense_rank: int | None = None



def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = RRF_K, weights: Sequence[float] | None = None) -> dict[str, float]:
    """(Weighted) Reciprocal Rank Fusion of ranked id lists (best first). Ranks are 1-based."""
    fused: dict[str, float] = {}
    for i, ranking in enumerate(rankings):
        w = weights[i] if weights is not None else 1.0
        for rank, doc_id in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + w / (k + rank)
    return fused


# Weight of the learned-embedding list in the fusion, relative to BM25 and the hashed embedder.
# Half until a real model has been compared on the eval set (`evals.run --dense voyage`).
DENSE_RRF_WEIGHT = 0.5


def hit_passes(
    hit: Hit,
    bm25_threshold: float = BM25_FOUND_THRESHOLD,
    cosine_threshold: float = COSINE_FOUND_THRESHOLD,
    dense_threshold: float | None = None,
) -> bool:
    """Does this single hit show the corpus covers the query? Plain ``Hit``s
    (BM25-only retrievers) fall back to ``score`` as the BM25 value."""
    if isinstance(hit, HybridHit):
        dense_ok = dense_threshold is not None and hit.dense >= dense_threshold
        return hit.bm25 >= bm25_threshold or hit.cosine >= cosine_threshold or dense_ok
    return hit.score >= bm25_threshold


def is_covered(hits: Sequence[Hit], dense_threshold: float | None = None) -> bool:
    """Query-level gate: some retrieved hit clears a raw-signal threshold."""
    return any(hit_passes(h, dense_threshold=dense_threshold) for h in hits)


def is_supported(hit: Hit, dense_threshold: float | None = None) -> bool:
    """Hit-level filter, applied only once ``is_covered`` holds: drop hits
    with no lexical match and cosine at noise level."""
    if isinstance(hit, HybridHit):
        dense_ok = dense_threshold is not None and hit.dense >= dense_threshold
        return hit.bm25 > 0.0 or hit.cosine >= COSINE_SUPPORT_FLOOR or dense_ok
    return hit.score >= BM25_FOUND_THRESHOLD


def gate(hits: Sequence[Hit], dense_threshold: float | None = None) -> list[Hit]:
    """Apply both gate levels. Returns [] when the query isn't covered."""
    if not is_covered(hits, dense_threshold):
        return []
    return [h for h in hits if is_supported(h, dense_threshold)]


class InvertedIndex:
    """Column-major (CSC) copy of the corpus matrix: for each hash bucket, the
    rows containing it and their weights.

    A query has ~50-300 non-zero buckets, so scoring touches only those
    posting lists instead of every stored value. That's O(sum of postings of
    the query buckets), not O(nnz(corpus)): about 10x faster than a full sparse
    dot product at 3k chunks.
    """

    def __init__(self, rows: SparseRows):
        self.n_rows = rows.n_rows
        order = np.argsort(rows.indices, kind="stable")
        row_of = np.repeat(np.arange(rows.n_rows, dtype=np.int32), np.diff(rows.indptr))
        self.rows = row_of[order]
        self.data = rows.data[order]
        self.colptr = np.zeros(rows.dim + 1, dtype=np.int64)
        np.cumsum(np.bincount(rows.indices, minlength=rows.dim), out=self.colptr[1:])

    def dot(self, q_idx: np.ndarray, q_val: np.ndarray) -> np.ndarray:
        """cosine(query, every row). Rows and query are unit-norm, so this is a dot product."""
        starts, ends = self.colptr[q_idx], self.colptr[q_idx + 1]
        lens = ends - starts
        total = int(lens.sum())
        if total == 0:
            return np.zeros(self.n_rows)
        # Flat positions of all postings for the query buckets, without a Python loop.
        offsets = np.repeat(starts - np.cumsum(lens) + lens, lens) + np.arange(total)
        weights = self.data[offsets] * np.repeat(q_val, lens)
        return np.bincount(self.rows[offsets], weights=weights, minlength=self.n_rows)


class HybridRetriever:
    """BM25 + embedding retrieval with RRF. Implements ``retrieval.Retriever``.

    The embedder is fitted on ``docs`` at construction time, so build one
    retriever per corpus and reuse it (``services.learning`` caches them).
    """

    def __init__(self, docs: Sequence[Indexable], embedder: Embedder):
        self.ids = [d.id for d in docs]
        self.bm25 = BM25Retriever(docs)
        texts = [f"{d.section} {d.text}" for d in docs]  # same view as BM25 (heading included)
        self.embedder = embedder.fit(texts)
        self._inverted: InvertedIndex | None = None
        self._dense: np.ndarray | None = None
        if not docs:
            return
        if isinstance(self.embedder, SparseEmbedder):
            self._inverted = InvertedIndex(self.embedder.embed_sparse(texts))
        else:
            self._dense = np.asarray(self.embedder.embed(texts), dtype=np.float32)

    def cosines(self, query: str) -> np.ndarray:
        """Cosine similarity of ``query`` to every doc, aligned with ``self.ids``."""
        if not self.ids:
            return np.zeros(0)
        if self._inverted is not None:
            assert isinstance(self.embedder, SparseEmbedder)
            q_idx, q_val = self.embedder.embed_sparse([query]).row(0)
            return self._inverted.dot(q_idx.astype(np.int64), q_val)
        assert self._dense is not None
        q = np.asarray(self.embedder.embed([query]), dtype=np.float32)[0]
        return self._dense @ q

    def search(self, query: str, k: int = 6, dense: dict[str, float] | None = None,
               dense_weight: float = DENSE_RRF_WEIGHT) -> list[HybridHit]:
        """``dense``: learned-embedding cosine per doc id (core.dense), fused as a third ranked list."""
        if not self.ids or not query.strip():
            return []
        bm25_hits = self.bm25.search(query, CANDIDATE_DEPTH)
        cos = self.cosines(query)
        depth = min(CANDIDATE_DEPTH, len(self.ids))
        top = np.argpartition(-cos, depth - 1)[:depth]
        # Sort by cosine descending, ties broken by corpus order, so results are deterministic.
        top = sorted((int(i) for i in top if cos[i] > 0.0), key=lambda i: (-cos[i], i))
        cos_ids = [self.ids[i] for i in top]

        dense = {i: v for i, v in (dense or {}).items() if i in set(self.ids)}
        dense_ids = [i for i, _ in sorted(dense.items(), key=lambda t: -t[1])[:CANDIDATE_DEPTH]]
        dense_rank = {doc_id: r for r, doc_id in enumerate(dense_ids, start=1)}
        fused = rrf_fuse([[h.id for h in bm25_hits], cos_ids] + ([dense_ids] if dense_ids else []),
                         weights=[1.0, 1.0] + ([dense_weight] if dense_ids else []))
        bm25_by_id = {h.id: (h.score, r) for r, h in enumerate(bm25_hits, start=1)}
        cos_rank = {doc_id: r for r, doc_id in enumerate(cos_ids, start=1)}
        index = {doc_id: i for i, doc_id in enumerate(self.ids)}

        hits = [
            HybridHit(
                doc_id,
                score,
                bm25=bm25_by_id.get(doc_id, (0.0, None))[0],
                cosine=float(cos[index[doc_id]]),
                bm25_rank=bm25_by_id.get(doc_id, (0.0, None))[1],
                cosine_rank=cos_rank.get(doc_id),
                dense=float(dense.get(doc_id, 0.0)),
                dense_rank=dense_rank.get(doc_id),
            )
            for doc_id, score in fused.items()
        ]
        hits.sort(key=lambda h: (-h.score, -h.cosine, index[h.id]))
        return hits[:k]
