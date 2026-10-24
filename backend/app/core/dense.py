"""Learned (dense) embeddings for retrieval (P2). Off unless DENSE_EMBEDDER is set.

Hybrid retrieval today fuses BM25 with a hashed char-n-gram embedder (core.hybrid). A learned
embedding model adds meaning-level matches ("how long jobs wait" ~ "queue time") as a third
ranked list in the same RRF fusion. It never replaces the lexical signals, and it only takes part
in the "is this covered?" gate once a threshold has been calibrated for that model
(`python -m evals.calibrate_dense`), because cosine scales differ a lot between models.

Providers:
  voyage  Voyage AI embeddings API (Anthropic's recommended embeddings partner); needs VOYAGE_API_KEY.
  fake    deterministic, offline, for tests and demos (word-stem hashing; NOT a real model).

Vectors are stored per chunk and model (app.models_embeddings), L2-normalised, so cosine is a dot
product. On Postgres with pgvector (`python -m app.tools.pgvector_setup`), nearest neighbours
can be searched in the database instead of in memory.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np

log = logging.getLogger("mindmesh.dense")


class DenseProvider(Protocol):
    name: str  # stored with each vector: "<provider>:<model>"
    dim: int

    def embed(self, texts: Sequence[str], input_type: str = "document") -> np.ndarray: ...


def normalise(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class FakeDenseProvider:
    """Offline stand-in: hashed word stems (+ a crude synonym fold) into 128 dims."""

    _FOLD = {"wait": "queue", "waiting": "queue", "waits": "queue", "queues": "queue", "delay": "queue",
             "inventory": "wip", "stock": "wip", "rate": "throughput", "output": "throughput"}

    def __init__(self, dim: int = 128):
        self.dim = dim
        self.name = "fake:stems-v1"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for w in "".join(c.lower() if c.isalnum() else " " for c in text).split():
            if len(w) < 3:
                continue
            w = self._FOLD.get(w, w)[:6]
            h = int(hashlib.blake2b(w.encode(), digest_size=4).hexdigest(), 16)
            v[h % self.dim] += 1.0
        return v

    def embed(self, texts: Sequence[str], input_type: str = "document") -> np.ndarray:
        return normalise(np.stack([self._vec(t) for t in texts])) if texts else np.zeros((0, self.dim), np.float32)


class VoyageProvider:
    """Voyage AI embeddings over HTTPS. Batches of 128; retries transient errors."""

    URL = "https://api.voyageai.com/v1/embeddings"
    BATCH = 128

    def __init__(self, api_key: str, model: str, dim: int, client=None, timeout: float = 30.0):
        import httpx

        self.dim, self.model, self.name = dim, model, f"voyage:{model}"
        self._key = api_key
        self._client = client or httpx.Client(timeout=timeout)
        self.last_tokens = 0

    def embed(self, texts: Sequence[str], input_type: str = "document") -> np.ndarray:
        import httpx

        out: list[list[float]] = []
        self.last_tokens = 0
        for i in range(0, len(texts), self.BATCH):
            body = {"input": list(texts[i:i + self.BATCH]), "model": self.model, "input_type": input_type,
                    "output_dimension": self.dim}
            for attempt in range(3):
                try:
                    r = self._client.post(self.URL, json=body, headers={"Authorization": f"Bearer {self._key}"})
                    if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                        time.sleep(0.5 * 2 ** attempt)
                        continue
                    r.raise_for_status()
                    data = r.json()
                    break
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                    time.sleep(0.5 * 2 ** attempt)
            rows = sorted(data["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in rows)
            self.last_tokens += int((data.get("usage") or {}).get("total_tokens") or 0)
        return normalise(np.asarray(out, dtype=np.float32)) if out else np.zeros((0, self.dim), np.float32)


def get_dense_provider(kind: str | None = None) -> DenseProvider | None:
    from ..config import get_settings

    s = get_settings()
    kind = (kind if kind is not None else s.dense_embedder).strip().lower()
    if kind == "fake":
        return FakeDenseProvider()
    if kind == "voyage":
        if not s.voyage_api_key:
            log.warning("DENSE_EMBEDDER=voyage but VOYAGE_API_KEY is not set; dense retrieval is off")
            return None
        return VoyageProvider(s.voyage_api_key, s.dense_model, s.dense_dim)
    return None


@dataclass
class DenseScorer:
    """Cosine of a query vector to stored chunk vectors (both normalised)."""
    ids: list[str]
    matrix: np.ndarray  # (n, dim)
    query: np.ndarray  # (dim,)

    def scores(self) -> dict[str, float]:
        if not self.ids:
            return {}
        sims = self.matrix @ self.query
        return {cid: float(s) for cid, s in zip(self.ids, sims)}


def to_bytes(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_bytes(b: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32, count=dim)
