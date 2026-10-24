"""Onboarding experiment: activation by arm (counts only, no user data).

    python -m app.tools.experiment_report [--since 2026-11-01]

Activation = a gap report on the user's own resume and a job, or a verified cited answer
plus an answered question (docs/ux-research.md). Retention = came back (any product event)
on a later day within 7 days of signing up. The primary window is 3 minutes from
sign-up; 1 and 7 days are shown too. Roughly 400 users per arm are needed to see a
10-point difference around a 50% rate (80% power, alpha 0.05); smaller samples are noise.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from ..jobs import system_context
from ..services.analytics import WINDOWS, experiment_summary

MIN_PER_ARM = 400


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Onboarding experiment report")
    p.add_argument("--since", help="only users exposed on or after this date (YYYY-MM-DD)")
    args = p.parse_args(argv)
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc) if args.since else None
    from ..db import SessionLocal

    with system_context(), SessionLocal() as db:
        s = experiment_summary(db, "onboarding", since)
    print(f"Experiment: {s['experiment']}" + (f" (exposed since {args.since})" if args.since else ""))
    labels = [label for label, _ in WINDOWS] + ["returned 7d"]
    print(f"{'arm':<14}{'exposed':>9}" + "".join(f"{label:>16}" for label in labels))
    for arm, row in s["arms"].items():
        n = row["exposed"]
        cells = "".join(f"{row[label]:>7} ({(row[label] / n * 100 if n else 0):5.1f}%)" for label in labels)
        print(f"{arm:<14}{n:>9}{cells}")
    print("p-value      " + " " * 9 + "".join(f"{('n/a' if v is None else f'{v:.3f}'):>16}" for v in s["p_values"].values()))
    small = [a for a, r in s["arms"].items() if r["exposed"] < MIN_PER_ARM]
    if small:
        print(f"Note: fewer than {MIN_PER_ARM} users in {', '.join(small)}; differences are not yet reliable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
