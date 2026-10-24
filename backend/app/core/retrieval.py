"""Lexical retrieval (BM25) over a user's chunks.

MVP choice: BM25 runs in-process with zero infrastructure and is strong on
the term-heavy questions users ask about textbooks ("what is Little's Law").
The `Retriever` interface lets us add pgvector semantic search and fuse the
rankings later (PRD 9.2 step 3) without touching callers.

Access control is NOT done here: callers must only pass chunks the current
user owns. The API layer enforces that with owner-scoped queries.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Protocol, Sequence

from .text import tokenize


@dataclass(frozen=True)
class Indexable:
    id: str
    text: str
    section: str = ""


@dataclass(frozen=True)
class Hit:
    id: str
    score: float


class Retriever(Protocol):
    def search(self, query: str, k: int = 6) -> list[Hit]: ...


class BM25Retriever:
    def __init__(self, docs: Sequence[Indexable], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.ids = [d.id for d in docs]
        # Section headings are weighted in by repeating them once.
        self.tfs = [Counter(tokenize(f"{d.section} {d.text}")) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg_len = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter[str] = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 6) -> list[Hit]:
        q_terms = list(dict.fromkeys(tokenize(query)))
        if not q_terms or not self.ids:
            return []
        hits: list[Hit] = []
        for i, tf in enumerate(self.tfs):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.lens[i] / (self.avg_len or 1))
            for t in q_terms:
                f = tf.get(t)
                if f:
                    score += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            if score > 0:
                hits.append(Hit(self.ids[i], score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
