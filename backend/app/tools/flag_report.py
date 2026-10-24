"""Question-quality report for operators, built from users' reports without reading their content.

    python -m app.tools.flag_report [--days 30] [--json]

Shows, per question generator (model@prompt version): questions generated, how many users
reported, the report rate, and the split by reason, question type and difficulty. It never
prints question text, answers, notes or anything identifying a user: generated questions
come from private documents. Use it to decide which prompt or model change to evaluate next.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..db import SessionLocal
from ..jobs import system_context
from ..models import Question, Quiz


def build_report(days: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with system_context():  # aggregate across users (RLS bypass for trusted server code)
        db = SessionLocal()
        try:
            totals = dict(db.execute(
                select(Question.generator_version, func.count())
                .join(Quiz, Quiz.id == Question.quiz_id)
                .where(Quiz.created_at >= since)
                .group_by(Question.generator_version)
            ).all())
            flagged = db.execute(
                select(Question.generator_version, Question.flag_reason, Question.qtype, Question.difficulty, func.count())
                .join(Quiz, Quiz.id == Question.quiz_id)
                .where(Quiz.created_at >= since, Question.flagged.is_not(None))
                .group_by(Question.generator_version, Question.flag_reason, Question.qtype, Question.difficulty)
            ).all()
        finally:
            db.close()
    rows: dict[str, dict] = {}
    for gen, total in totals.items():
        rows[gen] = {"generator": gen, "questions": total, "reported": 0,
                     "by_reason": defaultdict(int), "by_type": defaultdict(int), "by_difficulty": defaultdict(int)}
    for gen, reason, qtype, difficulty, n in flagged:
        r = rows[gen]
        r["reported"] += n
        r["by_reason"][reason or "other"] += n
        r["by_type"][qtype] += n
        r["by_difficulty"][difficulty] += n
    out = []
    for r in rows.values():
        r["report_rate"] = round(r["reported"] / r["questions"], 4) if r["questions"] else 0.0
        out.append({k: (dict(v) if isinstance(v, defaultdict) else v) for k, v in r.items()})
    return sorted(out, key=lambda r: (-r["report_rate"], r["generator"]))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    report = build_report(args.days)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    if not report:
        print(f"No quizzes in the last {args.days} days.")
        return 0
    print(f"Question reports, last {args.days} days (no question content shown)\n")
    print(f"{'generator':<40} {'questions':>9} {'reported':>8} {'rate':>6}  top reasons")
    for r in report:
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(r["by_reason"].items(), key=lambda kv: -kv[1])[:3]) or "-"
        print(f"{r['generator']:<40} {r['questions']:>9} {r['reported']:>8} {r['report_rate']:>6.1%}  {reasons}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
