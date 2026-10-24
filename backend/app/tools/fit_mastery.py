"""Fit the knowledge-tracing parameters to real attempts (prints them; changes nothing).

    python -m app.tools.fit_mastery [--min-sequences 200]

Grid-searches P_INIT and P_LEARN (the two that matter most) for the lowest log loss when
predicting each next answer from the ones before it, per learner x concept. Copy the result
into app/core/mastery.py once there is enough data (a few hundred sequences), then re-run
`python -m evals.mastery_eval` and the mastery tests. Reads scores, types and times only.
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict

from sqlalchemy import select

from ..core.mastery import P_INIT, P_LEARN, AttemptEvidence, knowledge_trace, p_correct
from ..jobs import system_context

GRID_INIT = [0.05, 0.1, 0.2, 0.3, 0.4, 0.5]
GRID_LEARN = [0.05, 0.1, 0.15, 0.2, 0.3, 0.4]


def log_loss(seqs: list[list[AttemptEvidence]], p_init: float, p_learn: float) -> float:
    total, n = 0.0, 0
    for seq in seqs:
        for i in range(1, len(seq)):
            nxt = seq[i]
            pk = knowledge_trace(seq[:i], nxt.at, p_init=p_init, p_learn=p_learn)
            p = min(1 - 1e-6, max(1e-6, p_correct(pk, nxt.qtype, nxt.difficulty)))
            y = 1 if nxt.score >= 0.85 else 0
            total -= y * math.log(p) + (1 - y) * math.log(1 - p)
            n += 1
    return total / n if n else float("nan")


def fit(seqs: list[list[AttemptEvidence]]) -> tuple[float, float, float]:
    """(p_init, p_learn, log_loss) with the lowest log loss on the grid."""
    return min(((pi, pl, log_loss(seqs, pi, pl)) for pi in GRID_INIT for pl in GRID_LEARN), key=lambda t: t[2])


def _sequences() -> list[list[AttemptEvidence]]:
    from ..db import SessionLocal
    from ..models import Attempt, Question

    by: dict[tuple[str, str], list[AttemptEvidence]] = defaultdict(list)
    with system_context(), SessionLocal() as db:
        rows = db.execute(select(Attempt.owner_id, Question.concept, Attempt.score, Question.qtype, Question.difficulty,
                                 Attempt.created_at, Attempt.verdict)
                          .join(Question, Question.id == Attempt.question_id)
                          .where(Question.flagged.is_(None)).order_by(Attempt.created_at)).all()
    for owner, concept, score, qtype, diff, at, verdict in rows:
        if verdict != "unassessed":
            by[(owner, concept)].append(AttemptEvidence(score, qtype, diff, at))
    return [s for s in by.values() if len(s) >= 2]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fit knowledge-tracing parameters")
    p.add_argument("--min-sequences", type=int, default=200)
    args = p.parse_args(argv)
    seqs = _sequences()
    print(f"{len(seqs)} learner x concept sequences with 2+ attempts")
    if len(seqs) < args.min_sequences:
        print(f"Not enough data to fit reliably (need {args.min_sequences}); keeping P_INIT={P_INIT}, P_LEARN={P_LEARN}.")
        return 0
    pi, pl, ll = fit(seqs)
    print(f"current: P_INIT={P_INIT} P_LEARN={P_LEARN} log loss {log_loss(seqs, P_INIT, P_LEARN):.4f}")
    print(f"best:    P_INIT={pi} P_LEARN={pl} log loss {ll:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
