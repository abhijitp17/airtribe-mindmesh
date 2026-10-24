"""Session wins and the weekly practice strip (CONTRACTS §7). Pure: no web or database code.

Wins compare the picture *before* a session's answers with the picture *after*:

* ``first_answer``: the user's first ever answer happened in this session.
* ``level_up``: a concept moved up a mastery level (weak < developing < strong).
  Going from "not enough answers yet" straight to weak is not a win.
* ``gap_closed``: a prep skill that was a gap is now strong.
* ``target_met``: the week's practised-day count reached the weekly target.

Titles use plain words, e.g. "Little's Law is now strong".
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

LEVEL_RANK = {"unverified": 0, "weak": 1, "developing": 2, "strong": 3}
LEVEL_WORD = {"unverified": "not rated yet", "weak": "weak", "developing": "developing", "strong": "strong"}
MAX_LEVEL_WINS = 5
MAX_GAP_WINS = 3


@dataclass(frozen=True)
class SkillState:
    """A prep skill's gap type before/after (keyed by prep id + competency id by the caller)."""
    name: str
    gap_type: str
    role_label: str = ""  # e.g. "Amazon" or the role title; optional


def _win(kind: str, title: str, detail: str) -> dict:
    return {"kind": kind, "title": title, "detail": detail}


def level_up_wins(before: Mapping[str, str], after: Mapping[str, str]) -> list[dict]:
    out = []
    for concept in sorted(after, key=lambda c: (-LEVEL_RANK.get(after[c], 0), c.casefold())):
        new = after[concept]
        old = before.get(concept, "unverified")
        if LEVEL_RANK.get(new, 0) <= LEVEL_RANK.get(old, 0) or new in ("unverified", "weak"):
            continue
        if old == "unverified":
            detail = "You've now answered enough questions for a rating."
        else:
            detail = f"It moved up from {LEVEL_WORD.get(old, old)} after this session."
        out.append(_win("level_up", f"{concept} is now {LEVEL_WORD[new]}", detail))
        if len(out) >= MAX_LEVEL_WINS:
            break
    return out


def gap_closed_wins(before: Mapping[str, SkillState], after: Mapping[str, SkillState]) -> list[dict]:
    out = []
    for key in sorted(after, key=lambda k: (after[k].name.casefold(), k)):
        new, old = after[key], before.get(key)
        if old is None or old.gap_type == "strong" or new.gap_type != "strong":
            continue
        where = f" for your {new.role_label} role" if new.role_label else ""
        out.append(_win("gap_closed", f"{new.name} is no longer a gap",
                        f"Your answers now show {new.name} is strong{where}."))
        if len(out) >= MAX_GAP_WINS:
            break
    return out


def compute_wins(
    *,
    levels_before: Mapping[str, str],
    levels_after: Mapping[str, str],
    attempts_before: int,
    attempts_in_session: int,
    skills_before: Mapping[str, SkillState] | None = None,
    skills_after: Mapping[str, SkillState] | None = None,
    week_done_before: int = 0,
    week_done_after: int = 0,
    weekly_target: int = 3,
) -> list[dict]:
    """Win[] for a completed session, most personal first."""
    wins: list[dict] = []
    if attempts_before == 0 and attempts_in_session > 0:
        wins.append(_win("first_answer", "You answered your first question",
                         "That's the start of seeing what you know."))
    wins += level_up_wins(levels_before, levels_after)
    wins += gap_closed_wins(skills_before or {}, skills_after or {})
    if weekly_target > 0 and week_done_before < weekly_target <= week_done_after:
        days = "day" if week_done_after == 1 else "days"
        wins.append(_win("target_met", "You hit your weekly target",
                         f"You practised on {week_done_after} {days} this week. Your target was {weekly_target}."))
    return wins


# ---------------- week ----------------

def week_start(today: date) -> date:
    """Monday of `today`'s week."""
    return today - timedelta(days=today.weekday())


def week_out(today: date, practised: Iterable[date], target: int) -> dict:
    """WeekOut for the Mon-Sun week containing `today`. `practised` may contain any dates."""
    start = week_start(today)
    days_set = {d for d in practised if start <= d <= start + timedelta(days=6)}
    days = [
        {"date": (start + timedelta(days=i)).isoformat(), "practised": (start + timedelta(days=i)) in days_set,
         "is_today": start + timedelta(days=i) == today}
        for i in range(7)
    ]
    return {"target": int(target), "done": len(days_set), "days": days}


def practised_dates(completed_session_dates: Iterable[date], attempt_dates: Iterable[date]) -> set[date]:
    """A day counts if a study session was completed OR any answer was submitted that day."""
    return set(completed_session_dates) | set(attempt_dates)


__all__ = ["LEVEL_RANK", "SkillState", "compute_wins", "gap_closed_wins", "level_up_wins", "practised_dates",
           "week_out", "week_start"]
