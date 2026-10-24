"""AI spend by task and model, from usage_events (no user content: task names and token counts only).

    python -m app.tools.cost_report [--days 7] [--json]

Prices are USD per million tokens (input, output), list prices when written (2026-10). Override
with MODEL_PRICES_JSON='{"claude-sonnet-5-5": [2, 10]}'. A stored model id matches the longest
price key it starts with, so dated ids ("claude-sonnet-4-5-20250929") are priced too; mock-* is free.
Reports cost per active user per day, the number to watch against pricing.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..db import SessionLocal
from ..jobs import system_context
from ..models import UsageEvent

DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),  # prompts up to 100K tokens
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def prices() -> dict[str, tuple[float, float]]:
    p = dict(DEFAULT_PRICES)
    p.update({k: tuple(v) for k, v in json.loads(os.getenv("MODEL_PRICES_JSON") or "{}").items()})
    return p


def price_for(model: str, table: dict[str, tuple[float, float]]) -> tuple[float, float] | None:
    if model.startswith("mock-"):
        return (0.0, 0.0)
    matches = [k for k in table if model.startswith(k)]
    return table[max(matches, key=len)] if matches else None


def build_report(days: int) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with system_context():  # aggregates across users (RLS bypass for trusted server code)
        db = SessionLocal()
        try:
            rows = db.execute(
                select(UsageEvent.task, UsageEvent.model, func.count(), func.sum(UsageEvent.input_tokens),
                       func.sum(UsageEvent.output_tokens))
                .where(UsageEvent.created_at >= since).group_by(UsageEvent.task, UsageEvent.model)
            ).all()
            users = db.scalar(select(func.count(func.distinct(UsageEvent.owner_id))).where(UsageEvent.created_at >= since)) or 0
        finally:
            db.close()
    table = prices()
    lines, total, unpriced = [], 0.0, set()
    for task, model, calls, tin, tout in rows:
        p = price_for(model, table)
        cost = None if p is None else (int(tin or 0) * p[0] + int(tout or 0) * p[1]) / 1_000_000
        if p is None:
            unpriced.add(model)
        total += cost or 0.0
        lines.append({"task": task, "model": model, "calls": int(calls), "input_tokens": int(tin or 0),
                      "output_tokens": int(tout or 0), "cost_usd": None if cost is None else round(cost, 4)})
    lines.sort(key=lambda r: -(r["cost_usd"] or 0))
    per_user_day = total / users / days if users and days else 0.0
    return {"days": days, "active_users": int(users), "total_usd": round(total, 4),
            "per_active_user_per_day_usd": round(per_user_day, 5), "unpriced_models": sorted(unpriced), "by_task": lines}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = build_report(args.days)
    if args.json:
        print(json.dumps(r, indent=2))
        return 0
    print(f"AI spend, last {r['days']} days: ${r['total_usd']:.2f} across {r['active_users']} active users "
          f"(${r['per_active_user_per_day_usd']:.4f} per active user per day)\n")
    print(f"{'task':<20}{'model':<32}{'calls':>7}{'in tok':>11}{'out tok':>10}{'USD':>10}")
    for x in r["by_task"]:
        usd = "unpriced" if x["cost_usd"] is None else f"{x['cost_usd']:.2f}"
        print(f"{x['task']:<20}{x['model'][:31]:<32}{x['calls']:>7}{x['input_tokens']:>11}{x['output_tokens']:>10}{usd:>10}")
    if r["unpriced_models"]:
        print(f"\nNo price for: {', '.join(r['unpriced_models'])} (set MODEL_PRICES_JSON)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
