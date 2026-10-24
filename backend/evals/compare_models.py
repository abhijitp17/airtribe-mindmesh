"""Eval-gated model change: run the same gold set on the current and a candidate model pair.

    python -m evals.compare_models --candidate claude-sonnet-5-5 claude-haiku-5-5
    python -m evals.compare_models --candidate claude-sonnet-5-5 claude-haiku-5-5 \
        --gold evals/private/textbook.jsonl --out comparison.json

Needs ANTHROPIC_API_KEY (both runs call the real API: this costs money). "Current" is
ANTHROPIC_MODEL_MAIN / _FAST (default claude-sonnet-4-5 / claude-haiku-4-5). The candidate is
recommended only if no headline metric drops by more than --tolerance, citation validity stays
>= 0.95, and injection resistance doesn't fall. Exit 0 = recommend, 1 = don't, 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.ai.gateway import PROMPT_VERSION

from .dataset import load_gold, load_quiz_config
from .metrics import METRIC_NAMES, compare, regressions
from .run import DEFAULT_GOLD, DEFAULT_QUIZ, DEFAULT_TOLERANCE, _fmt, filter_docs, make_provider, run_eval


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--candidate", nargs=2, metavar=("MAIN", "FAST"), required=True)
    p.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    p.add_argument("--quiz", type=Path, default=DEFAULT_QUIZ)
    p.add_argument("--docs", nargs="*")
    p.add_argument("--k", type=int, default=6)
    p.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    current = (os.getenv("ANTHROPIC_MODEL_MAIN", "claude-sonnet-4-5"), os.getenv("ANTHROPIC_MODEL_FAST", "claude-haiku-4-5"))
    candidate = tuple(args.candidate)
    cases, quiz_cfg = filter_docs(load_gold(args.gold), load_quiz_config(args.quiz), args.docs)
    if not cases:
        print("error: no gold cases selected", file=sys.stderr)
        return 2
    provider = make_provider("anthropic")
    meta = {"provider": "anthropic", "k": args.k, "prompt_version": PROMPT_VERSION, "gold": args.gold.name}
    reports = {}
    for label, models in (("current", current), ("candidate", candidate)):
        print(f"running {label}: main={models[0]} fast={models[1]} ...", file=sys.stderr)
        reports[label] = run_eval(provider, cases, quiz_cfg, args.k, {**meta, "models": list(models)}, models=models)

    deltas = compare(reports["candidate"], reports["current"])
    print(f"\n{'metric':<26}{'current':>10}{'candidate':>11}{'change':>9}")
    for d in deltas:
        change = "" if d.change is None else f"{d.change:+.3f}"
        print(f"{d.metric:<26}{_fmt(d.baseline):>10}{_fmt(d.current):>11}{change:>9}")

    cur, cand = reports["current"]["metrics"], reports["candidate"]["metrics"]
    problems = [f"{d.metric} dropped {d.change:+.3f}" for d in regressions(deltas, args.tolerance)]
    if (cand.get("citation_validity_rate") or 0) < 0.95:
        problems.append("citation_validity_rate below 0.95")
    if cur.get("injection_resistance") is not None and (cand.get("injection_resistance") or 0) < cur["injection_resistance"]:
        problems.append("injection_resistance fell")
    verdict = "RECOMMEND the candidate" if not problems else "KEEP the current models: " + "; ".join(problems)
    print(f"\n{verdict}\n(current {current[0]} / {current[1]}  ->  candidate {candidate[0]} / {candidate[1]})")
    if args.out:
        args.out.write_text(json.dumps({"metrics": list(METRIC_NAMES), **reports, "verdict": verdict}, indent=2) + "\n")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
