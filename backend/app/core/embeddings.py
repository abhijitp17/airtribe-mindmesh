"""Text embedders for the vector half of hybrid retrieval (CONTRACTS §5).

Two layers:

* ``Embedder`` is the public contract. ``fit(corpus)`` returns an embedder
  ready for that corpus, and ``embed(texts)`` returns a dense, L2-normalised
  ``float32`` array of shape ``(len(texts), dim)``. Cosine similarity is then
  just a dot product.
* ``SparseEmbedder`` is an optional fast path. Embedders whose vectors are
  mostly zeros (the hashing embedder has ~2^18 dims and ~1-3k non-zeros per
  chunk) can also return ``SparseRows``. ``HybridRetriever`` uses it when it's
  available, because a dense 3,000 x 262,144 matrix would need about 3 GB.

``HashingEmbedder`` is the default (``EMBEDDER=hash``). It has no dependencies
beyond numpy and needs no network or model weights. It's a TF-IDF vector over
hashed features from three families:

* stemmed word unigrams (``app.core.text.tokenize``, the same as BM25)
* stemmed word bigrams (local phrase/word order, e.g. "cycle time")
* character 3-5-grams inside each word, with ``<``/``>`` word-boundary
  markers (fastText style). These match morphological variants the tiny
  stemmer misses ("operational" ~ "operations", "capitalisation" ~
  "capital") and survive typos and OCR noise.

Each family block is TF-IDF weighted (sublinear tf, smoothed idf fitted on the
corpus being searched), L2-normalised on its own, and then scaled by
``sqrt(w_family)``. This makes cosine(q, d) = sum_f w_f * cos_f(q, d), a
convex mix of per-family cosines. The character family has ~10x as many
features as the word family, so without this per-block normalisation it would
dominate.

This embedder captures surface and sub-word similarity, not meaning. It
doesn't know that "money" and "capital" are related. Real semantic recall
needs a learned model, plugged in at the extension point below.

Extension point (real models)
-----------------------------
To add a learned model, such as sentence-transformers locally or a hosted
embedding API:

1. Implement a class with ``name: str`` (include the model id, so the
   retrieval cache in ``services.learning`` is keyed correctly), ``dim``,
   ``fit(corpus) -> self`` (pretrained models don't need corpus statistics),
   and ``embed(texts) -> np.ndarray`` (L2-normalised rows).
2. Add a branch for its setting value in ``get_embedder()`` below.
3. Re-calibrate ``hybrid.COSINE_FOUND_THRESHOLD`` for that model, because
   cosine scales differ a lot between embedders (see hybrid.py).

Chunk vectors should then be computed at ingestion and stored (pgvector),
not recomputed per query. The ``fit`` / ``embed`` split already allows that.
"""
from __future__ import annotations

import logging
import math
import re
import zlib
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, Sequence, runtime_checkable

import numpy as np

from .text import STOPWORDS, normalize, stem

log = logging.getLogger("mindmesh.embeddings")

# 2^18 hash buckets. A 5k-chunk corpus has roughly 100k-300k distinct
# features, so many features share a bucket. Sign hashing (a hash bit picks
# +1/-1) makes the expected contribution of a collision to a dot product zero,
# so cosine stays unbiased (Weinberger et al., 2009).
# Cost per bucket: 3 float32 idf arrays plus an int64 CSC column pointer (~20 B).
HASH_DIM = 1 << 18

# Character n-gram range inside words. 3-5 is the fastText default and the
# usual sweet spot: 2-grams are too unspecific, and >5 adds little over the
# word itself.
CHAR_NGRAM_MIN, CHAR_NGRAM_MAX = 3, 5

# Family weights (they sum to 1, so cosine stays in [-1, 1]). Words carry the
# topical signal, char-grams the morphological recall, and bigrams a little
# phrase precision. Chosen on the tests/test_retrieval_v2.py sets: char
# weights 0.3-0.6 all give the same recall. Off-topic noise grows with the char
# weight (max cosine 0.044 at 0.40 vs 0.066 at 0.60), so 0.40 keeps the widest
# margin under hybrid.COSINE_FOUND_THRESHOLD.
FAMILY_WEIGHTS: dict[str, float] = {"word": 0.45, "bigram": 0.15, "char": 0.40}

_WORD_RE = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")

# A hashed feature is encoded as one int64 key: crc32 masked to
# 2 * HASH_DIM values. ``key >> 1`` is the bucket and ``key & 1`` the sign bit.
# Keeping features as integer arrays lets the per-chunk work run in numpy.
_KEY_MASK = 2 * HASH_DIM - 1

# Per-word cache of hashed char-gram keys. Word frequencies follow Zipf's
# law, so most lookups hit, and this is what makes fitting ~5k chunks fast.
# The cache is bounded so a pathological corpus can't grow memory without limit.
_CHAR_CACHE: dict[str, np.ndarray] = {}
_CHAR_CACHE_MAX = 200_000

# One family's features for one text: (unique keys, raw term counts).
FamilyFeatures = tuple[np.ndarray, np.ndarray]


def _key(feature: str) -> int:
    """Stable (process-independent) hash.

    crc32 is used instead of Python ``hash()``, which is salted per process
    and would make vectors differ between workers and restarts.
    """
    return zlib.crc32(feature.encode("utf-8")) & _KEY_MASK


def _char_keys(word: str) -> np.ndarray:
    cached = _CHAR_CACHE.get(word)
    if cached is not None:
        return cached
    padded = f"<{word}>"
    grams = {
        padded[i : i + n]
        for n in range(CHAR_NGRAM_MIN, CHAR_NGRAM_MAX + 1)
        for i in range(len(padded) - n + 1)
    }
    keys = np.fromiter((_key("c:" + g) for g in grams), dtype=np.int64, count=len(grams))
    if len(_CHAR_CACHE) >= _CHAR_CACHE_MAX:
        _CHAR_CACHE.clear()
    _CHAR_CACHE[word] = keys
    return keys


def _count(keys: np.ndarray, weights: np.ndarray | None = None) -> FamilyFeatures:
    if keys.size == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.float32)
    uniq, inv = np.unique(keys, return_inverse=True)
    return uniq, np.bincount(inv, weights=weights).astype(np.float32)


@lru_cache(maxsize=200_000)
def _stem_key(word: str) -> tuple[str, int]:
    """(stem, hashed word key), memoised. ``text.stem`` is the hot spot of
    fitting (it's a Python suffix loop), and a corpus repeats words heavily."""
    s = stem(word)
    return s, _key("w:" + s)


def extract_features(text: str) -> dict[str, FamilyFeatures]:
    """Raw hashed term counts per family."""
    raw = [w for w in _WORD_RE.findall(normalize(text)) if w not in STOPWORDS]
    pairs = [_stem_key(w) for w in raw]
    stems = [p[0] for p in pairs]
    words = np.fromiter((p[1] for p in pairs), dtype=np.int64, count=len(pairs))
    bigrams = np.fromiter(
        (_key(f"b:{a} {b}") for a, b in zip(stems, stems[1:])), dtype=np.int64,
        count=max(0, len(stems) - 1),
    )
    word_counts = Counter(raw)
    if word_counts:
        arrays = [_char_keys(w) for w in word_counts]
        chars = np.concatenate(arrays)
        reps = np.repeat(
            np.fromiter(word_counts.values(), dtype=np.float64, count=len(word_counts)),
            [len(a) for a in arrays],
        )
    else:
        chars, reps = np.zeros(0, np.int64), None
    return {"word": _count(words), "bigram": _count(bigrams), "char": _count(chars, reps)}


@dataclass(frozen=True)
class SparseRows:
    """Minimal CSR matrix (no scipy dependency). Row i is
    ``indices[indptr[i]:indptr[i+1]]`` with matching ``data``."""

    indptr: np.ndarray  # int64, shape (n_rows + 1,)
    indices: np.ndarray  # int32 column ids, sorted and unique within each row
    data: np.ndarray  # float32
    dim: int

    @property
    def n_rows(self) -> int:
        return len(self.indptr) - 1

    def row(self, i: int) -> tuple[np.ndarray, np.ndarray]:
        a, b = self.indptr[i], self.indptr[i + 1]
        return self.indices[a:b], self.data[a:b]

    def to_dense(self) -> np.ndarray:
        out = np.zeros((self.n_rows, self.dim), dtype=np.float32)
        rows = np.repeat(np.arange(self.n_rows), np.diff(self.indptr))
        out[rows, self.indices] = self.data
        return out


class Embedder(Protocol):
    """Public embedding contract. Rows returned by ``embed`` are L2-normalised."""

    name: str

    @property
    def dim(self) -> int: ...

    def fit(self, corpus: Sequence[str]) -> "Embedder":
        """Return an embedder ready to embed this corpus and queries against it.
        Corpus-statistics models (TF-IDF) learn IDF here; pretrained models return self."""
        ...

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


@runtime_checkable
class SparseEmbedder(Protocol):
    """Optional fast path for embedders with very high-dimensional sparse output."""

    def embed_sparse(self, texts: Sequence[str]) -> SparseRows: ...


class HashingEmbedder:
    """Hashed word/bigram/char-n-gram TF-IDF embedder. See the module docstring."""

    name = "hash-v1"  # bump if features or weights change (it's part of the cache key)

    def __init__(self, idf: dict[str, np.ndarray] | None = None, n_docs: int = 0):
        # idf[family] is a dense float32 array over HASH_DIM. Unseen buckets
        # get the maximum idf, log((1+N)/1) + 1.
        self._idf = idf
        self._n_docs = n_docs
        # Features of the corpus passed to fit(), kept once so the immediately
        # following embed_sparse(corpus) doesn't re-tokenise it.
        self._cached_corpus: tuple[list[str], list[dict[str, FamilyFeatures]]] | None = None

    @property
    def dim(self) -> int:
        return HASH_DIM

    @property
    def is_fitted(self) -> bool:
        return self._idf is not None

    def fit(self, corpus: Sequence[str]) -> "HashingEmbedder":
        feats = [extract_features(t) for t in corpus]
        fitted = HashingEmbedder(self._idf_from(feats), len(corpus))
        fitted._cached_corpus = (list(corpus), feats)
        return fitted

    @staticmethod
    def _idf_from(feats: list[dict[str, FamilyFeatures]]) -> dict[str, np.ndarray]:
        n = len(feats)
        idf: dict[str, np.ndarray] = {}
        for fam in FAMILY_WEIGHTS:
            buckets = [np.unique(f[fam][0] >> 1) for f in feats if f[fam][0].size]
            df = (
                np.bincount(np.concatenate(buckets), minlength=HASH_DIM).astype(np.float32)
                if buckets else np.zeros(HASH_DIM, np.float32)
            )
            # Smoothed idf, as in scikit-learn: log((1+N)/(1+df)) + 1. It's
            # always > 0, so terms present in every doc still count a little.
            idf[fam] = (np.log((1.0 + n) / (1.0 + df)) + 1.0).astype(np.float32)
        return idf

    def _row(self, f: dict[str, FamilyFeatures]) -> tuple[np.ndarray, np.ndarray]:
        assert self._idf is not None
        cols: list[np.ndarray] = []
        vals: list[np.ndarray] = []
        for fam, weight in FAMILY_WEIGHTS.items():
            keys, tf = f[fam]
            if keys.size == 0:
                continue
            b = keys >> 1
            sign = 1.0 - 2.0 * (keys & 1).astype(np.float32)
            v = sign * (1.0 + np.log(tf)) * self._idf[fam][b]  # sublinear tf * idf
            norm = float(np.linalg.norm(v))
            if norm == 0.0:
                continue
            cols.append(b)
            vals.append(v * (math.sqrt(weight) / norm))
        if not cols:
            return np.zeros(0, np.int32), np.zeros(0, np.float32)
        # Merge bucket collisions (within and across families), then
        # renormalise to exactly unit length.
        uniq, inv = np.unique(np.concatenate(cols), return_inverse=True)
        merged = np.bincount(inv, weights=np.concatenate(vals)).astype(np.float32)
        norm = float(np.linalg.norm(merged))
        if norm > 0:
            merged /= norm
        return uniq.astype(np.int32), merged

    def embed_sparse(self, texts: Sequence[str]) -> SparseRows:
        if self._idf is None:
            raise RuntimeError("HashingEmbedder must be fit() on the corpus before embedding.")
        cached = self._cached_corpus
        if cached is not None and cached[0] == list(texts):
            feats = cached[1]
            self._cached_corpus = None  # one-shot, so the corpus features don't stay in memory
        else:
            feats = [extract_features(t) for t in texts]
        indptr = np.zeros(len(feats) + 1, dtype=np.int64)
        all_c: list[np.ndarray] = []
        all_v: list[np.ndarray] = []
        for i, f in enumerate(feats):
            c, v = self._row(f)
            all_c.append(c)
            all_v.append(v)
            indptr[i + 1] = indptr[i] + len(c)
        indices = np.concatenate(all_c) if all_c else np.zeros(0, np.int32)
        data = np.concatenate(all_v) if all_v else np.zeros(0, np.float32)
        return SparseRows(indptr, indices.astype(np.int32), data.astype(np.float32), HASH_DIM)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Dense rows (len(texts) x 2^18 float32, i.e. 1 MB per row). Fine for
        queries and small batches; use ``embed_sparse`` for corpora."""
        return self.embed_sparse(texts).to_dense()


def get_embedder(kind: str | None = None) -> Embedder | None:
    """Embedder selected by ``settings.embedder`` ("hash" | "none").

    ``None`` means "lexical only": callers fall back to BM25.
    """
    if kind is None:
        from ..config import get_settings

        kind = get_settings().embedder
    kind = (kind or "").strip().lower()
    if kind == "hash":
        return HashingEmbedder()
    if kind in ("none", "off", ""):
        return None
    # Extension point: add learned-model branches here (see the module docstring).
    log.warning("unknown EMBEDDER=%r; falling back to lexical-only retrieval", kind)
    return None
