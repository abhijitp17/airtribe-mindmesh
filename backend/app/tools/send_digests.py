"""Send any reminder / weekly-summary emails that are due now (worker.py does this every 5 minutes).

    python -m app.tools.send_digests

Useful without a worker (JOB_BACKEND=inline in dev) or from cron. Idempotent: running it
twice sends nothing new.
"""
from __future__ import annotations

from ..services.digests import run_due


def main() -> int:
    c = run_due()
    print(f"checked {c['checked']} users with reminders on: {c['reminder']} reminders, {c['weekly']} weekly summaries sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
