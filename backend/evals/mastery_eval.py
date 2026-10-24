"""Mastery model check: does knowledge tracing predict the next answer better than the old rules?

    python -m evals.mastery_eval [--learners 400] [--seed 7] [--fail-if-worse]

Simulated learners, deliberately NOT drawn from either model: each has a continuous skill
level per concept that grows with practice (with diminishing returns), fades over gaps of
days, and answers like an item-response model (a guess floor that depends on the question
type, then a logistic curve in skill minus difficulty). For every attempt after the first,
each model predicts the chance of a correct answer from the attempts before it; we compare
log loss, Brier score and AUC. Lower log loss / Brier and higher AUC are better.

This is a sanity check, not a substitute for real data: once real attempts exist, fit the
parameters with `python -m app.tools.fit_mastery` and re-run against held-out learners.
"""
from __future__ import annotations

import argparse
import math
import random
from datetime import datetime, timedelta, timezone

from app.core.mastery import AttemptEvidence, estimate_rules, knowledge_trace, p_correct

GUESS = {"mcq": 0.25, "short": 0.05, "applied": 0.03}
DIFF_B = {"easy": -0.8, "medium": 0.0, "hard": 0.8}
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def simulate(n_learners: int, seed: int) -> list[list[tuple[AttemptEvidence, int]]]:
    rng = random.Random(seed)
    seqs = []
    for _ in range(n_learners):
        theta = rng.gauss(-1.0, 1.0)  # most start without the concept
        rate = rng.uniform(0.1, 0.6)
        t = START
        seq = []
        for _ in range(rng.randint(3, 14)):
            t += timedelta(days=rng.choice([0, 0, 1, 1, 2, 3, 7, 14, 30]), minutes=rng.randint(1, 120))
            if seq:
                gap = (t - seq[-1][0].at).total_seconds() / 86400
                theta -= 0.02 * gap  # forgetting
            qtype = rng.choice(["mcq", "mcq", "short", "applied"])
            diff = rng.choice(["easy", "medium", "medium", "hard"])
            p = GUESS[qtype] + (1 - GUESS[qtype]) / (1 + math.exp(-(theta - DIFF_B[diff]) * 1.7))
            correct = 1 if rng.random() < p else 0
            score = float(correct) if qtype == "mcq" else (correct * rng.uniform(0.85, 1.0) + (1 - correct) * rng.uniform(0.0, 0.5))
            seq.append((AttemptEvidence(score, qtype, diff, t), correct))
            theta += rate * (1.2 - 0.3 * max(0.0, theta))  # practice with feedback teaches, less as you improve
        seqs.append(seq)
    return seqs


def _auc(pairs: list[tuple[float, int]]) -> float:
    pos = [p for p, y in pairs if y]
    neg = [p for p, y in pairs if not y]
    if not pos or not neg:
        return float("nan")
    ranked = sorted(pairs, key=lambda t: t[0])
    rank_sum, i = 0.0, 0
    while i < len(ranked):  # average ranks for ties
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        avg = (i + j + 1) / 2
        rank_sum += avg * sum(y for _, y in ranked[i:j])
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def evaluate(seqs) -> dict[str, dict[str, float]]:
    preds: dict[str, list[tuple[float, int]]] = {"bkt": [], "rules": []}
    for seq in seqs:
        for i in range(1, len(seq)):
            history = [a for a, _ in seq[:i]]
            nxt, y = seq[i]
            pk = knowledge_trace(history, nxt.at)
            preds["bkt"].append((p_correct(pk, nxt.qtype, nxt.difficulty), y))
            r = estimate_rules("c", history, now=nxt.at).estimate
            preds["rules"].append((p_correct(r, nxt.qtype, nxt.difficulty), y))
    out = {}
    for name, pairs in preds.items():
        eps = 1e-6
        ll = -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p)) for p, y in pairs) / len(pairs)
        brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
        out[name] = {"log_loss": round(ll, 4), "brier": round(brier, 4), "auc": round(_auc(pairs), 4), "n": len(pairs)}
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--learners", type=int, default=400)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--fail-if-worse", action="store_true", help="exit 1 if knowledge tracing loses on log loss")
    args = p.parse_args(argv)
    res = evaluate(simulate(args.learners, args.seed))
    print(f"{'model':<8}{'log loss':>10}{'brier':>9}{'AUC':>8}{'n':>7}")
    for name, m in res.items():
        print(f"{name:<8}{m['log_loss']:>10.4f}{m['brier']:>9.4f}{m['auc']:>8.4f}{m['n']:>7}")
    if args.fail_if_worse and res["bkt"]["log_loss"] > res["rules"]["log_loss"]:
        print("FAIL: knowledge tracing predicts worse than the rules")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
