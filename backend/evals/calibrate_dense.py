"""Calibrate the coverage threshold for a learned embedding model (core.dense).

    python -m evals.calibrate_dense [--dense voyage|fake]

For each gold question, the best dense cosine over its document's chunks. A threshold lets dense
retrieval decide "covered" only if it keeps not_found recall at 1.0 (no off-topic question
passes). Recommends the lowest such threshold (max not_found cosine + a margin) and reports how
many answerable questions clear it. Put the value in DENSE_FOUND_THRESHOLD; until then dense
retrieval only re-ranks.
"""
from __future__ import annotations

import argparse

from app.core.dense import get_dense_provider

from .corpus import load_doc
from .dataset import load_gold
from .run import DEFAULT_GOLD, DenseIndex

MARGIN = 0.02


def best_cosines(provider, gold=DEFAULT_GOLD) -> list[tuple[str, str, float]]:
    """[(case id, expect, best cosine)]"""
    cases = load_gold(gold)
    index = DenseIndex(provider)
    docs = {c.doc: load_doc(c.doc) for c in cases}
    return [(c.id, c.expect, max(index.scores(docs[c.doc].chunks, c.question).values(), default=0.0)) for c in cases]


def recommend(rows: list[tuple[str, str, float]]) -> tuple[float, float]:
    """(threshold, share of answerable questions at or above it)."""
    off = [v for _, e, v in rows if e == "not_found"]
    on = [v for _, e, v in rows if e != "not_found"]
    t = round((max(off) if off else 0.0) + MARGIN, 3)
    return t, (sum(v >= t for v in on) / len(on) if on else 0.0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dense", choices=("voyage", "fake"), default="voyage")
    args = p.parse_args(argv)
    provider = get_dense_provider(args.dense)
    if provider is None:
        print("dense provider unavailable (set VOYAGE_API_KEY)")
        return 2
    rows = best_cosines(provider)
    off = sorted(v for _, e, v in rows if e == "not_found")
    on = sorted(v for _, e, v in rows if e != "not_found")
    print(f"model {provider.name}: answerable best-cosine min/median {on[0]:.3f}/{on[len(on) // 2]:.3f}; "
          f"not_found max {off[-1]:.3f}")
    t, share = recommend(rows)
    print(f"recommended DENSE_FOUND_THRESHOLD={t} (answerable questions it alone would admit: {share:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
