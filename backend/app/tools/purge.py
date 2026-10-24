"""Delete records past their retention period (worker.py runs this hourly).

    python -m app.tools.purge [--dry-run]

Periods come from RETENTION_*_DAYS (0 = keep). See app/services/retention.py and
docs/legal/retention-policy.md.
"""
from __future__ import annotations

import argparse

from ..services.retention import run_purge


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mindmesh retention purge")
    p.add_argument("--dry-run", action="store_true", help="count what would be deleted; delete nothing")
    args = p.parse_args(argv)
    counts = run_purge(dry_run=args.dry_run)
    verb = "would delete" if args.dry_run else "deleted"
    if not counts:
        print("nothing to purge: every retention period is 0 (keep)")
    for name, n in counts.items():
        print(f"{name}: {verb} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
