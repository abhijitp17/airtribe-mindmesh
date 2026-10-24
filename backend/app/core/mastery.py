"""Mastery estimate per user x concept (PRD 8.3): knowledge tracing since P2.

`estimate` uses Bayesian Knowledge Tracing (BKT): the probability the learner knows the
concept, updated by each answer. Guessing depends on the question type (a 4-option MCQ is
easy to guess, an applied answer isn't), slips and guesses shift with difficulty, partial
scores count as partial evidence, and knowledge not practised for a long time drifts back
towards the prior. `estimate_rules` is the earlier weighted average, kept for comparison
(evals/mastery_eval.py). Both are recomputed from raw attempts, so changing the model never
loses data. The PRD's design rules still hold:

* One correct MCQ is never proof of mastery: fewer than MIN_EVIDENCE attempts
  is reported as "unverified", which is shown differently from "weak".
* Application questions count more than recall.
* Old evidence decays (half-life), so stale knowledge resurfaces for revision.
* Every estimate carries a human-readable explanation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# ---- knowledge tracing parameters (fit with `python -m app.tools.fit_mastery` once real attempts exist)
P_INIT = 0.2  # knew it before practising here
P_LEARN = 0.15  # learns it from one practice attempt (with feedback)
P_SLIP = 0.1  # knows it but answers wrongly
P_GUESS = {"mcq": 0.25, "short": 0.08, "applied": 0.05}  # right without knowing it
DIFFICULTY_SHIFT = {"easy": (-0.04, 0.05), "medium": (0.0, 0.0), "hard": (0.05, -0.03)}  # (slip, guess)
FORGET_HALF_LIFE_DAYS = 90.0  # unpractised knowledge drifts back towards P_INIT (reviews are scheduled separately)

TYPE_WEIGHT = {"mcq": 1.0, "short": 1.5, "applied": 2.0}
DIFFICULTY_WEIGHT = {"easy": 0.8, "medium": 1.0, "hard": 1.25}
HALF_LIFE_DAYS = 14.0
MIN_EVIDENCE = 3
STRONG, DEVELOPING = 0.8, 0.5


@dataclass
class AttemptEvidence:
    score: float
    qtype: str
    difficulty: str
    at: datetime


@dataclass
class MasteryEstimate:
    concept: str
    estimate: float
    level: str  # unverified | weak | developing | strong
    evidence_count: int
    last_assessed_at: datetime | None
    due_for_review: bool
    explanation: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _slip_guess(qtype: str, difficulty: str) -> tuple[float, float]:
    ds, dg = DIFFICULTY_SHIFT.get(difficulty, (0.0, 0.0))
    return min(0.3, max(0.01, P_SLIP + ds)), min(0.4, max(0.01, P_GUESS.get(qtype, 0.1) + dg))


def _forget(p: float, days: float) -> float:
    return P_INIT + (p - P_INIT) * 0.5 ** (max(0.0, days) / FORGET_HALF_LIFE_DAYS)


def knowledge_trace(attempts: list[AttemptEvidence], now: datetime | None = None,
                    p_init: float = P_INIT, p_learn: float = P_LEARN) -> float:
    """P(knows the concept) now, after the attempts in time order."""
    p, last = p_init, None
    for a in sorted(attempts, key=lambda a: _aware(a.at)):
        at = _aware(a.at)
        if last is not None:
            p = _forget(p, (at - last).total_seconds() / 86400)
        slip, guess = _slip_guess(a.qtype, a.difficulty)
        s = max(0.0, min(1.0, a.score))  # partial credit is partial evidence
        like_known = s * (1 - slip) + (1 - s) * slip
        like_unknown = s * guess + (1 - s) * (1 - guess)
        p = p * like_known / (p * like_known + (1 - p) * like_unknown)
        p = p + (1 - p) * p_learn  # practising with feedback teaches
        last = at
    if last is not None and now is not None:
        p = _forget(p, (now - last).total_seconds() / 86400)
    return p


def p_correct(p_known: float, qtype: str, difficulty: str = "medium") -> float:
    """Predicted chance of answering the next question right (used to evaluate the model)."""
    slip, guess = _slip_guess(qtype, difficulty)
    return p_known * (1 - slip) + (1 - p_known) * guess


def estimate(concept: str, attempts: list[AttemptEvidence], now: datetime | None = None) -> MasteryEstimate:
    """Knowledge-tracing estimate (see module docstring)."""
    now = now or _now()
    if not attempts:
        return MasteryEstimate(concept, 0.0, "unverified", 0, None, False, "Not assessed yet.")
    return _finish(concept, attempts, knowledge_trace(attempts, now), now)


def estimate_rules(concept: str, attempts: list[AttemptEvidence], now: datetime | None = None) -> MasteryEstimate:
    """The pre-P2 weighted average with a 14-day half-life (kept for comparison)."""
    now = now or _now()
    if not attempts:
        return MasteryEstimate(concept, 0.0, "unverified", 0, None, False, "Not assessed yet.")

    num = den = 0.0
    for a in attempts:
        age_days = max(0.0, (now - _aware(a.at)).total_seconds() / 86400)
        decay = 0.5 ** (age_days / HALF_LIFE_DAYS)
        w = TYPE_WEIGHT.get(a.qtype, 1.0) * DIFFICULTY_WEIGHT.get(a.difficulty, 1.0) * decay
        num += w * max(0.0, min(1.0, a.score))
        den += w
    return _finish(concept, attempts, num / den if den else 0.0, now)


def _finish(concept: str, attempts: list[AttemptEvidence], value: float, now: datetime) -> MasteryEstimate:
    last = max(_aware(a.at) for a in attempts)
    n = len(attempts)
    correct = sum(1 for a in attempts if a.score >= 0.85)
    applied = [a for a in attempts if a.qtype == "applied"]
    applied_ok = sum(1 for a in applied if a.score >= 0.85)

    if n < MIN_EVIDENCE:
        level = "unverified"
    elif value >= STRONG:
        level = "strong"
    elif value >= DEVELOPING:
        level = "developing"
    else:
        level = "weak"

    # Review interval grows with mastery; weak concepts come back quickly.
    interval_days = 1 + 13 * value ** 2
    due = now - last >= timedelta(days=interval_days) or level == "weak"

    explanation = _explain(n, correct, len(applied), applied_ok, (now - last).days)
    return MasteryEstimate(concept, round(value, 3), level, n, last, due, explanation)


def _applied_clause(total: int, ok: int) -> str:
    """Plain-language note on application questions, e.g. 'including both application questions'."""
    noun = "application question" if total == 1 else "application questions"
    if ok == total:
        if total == 1:
            return f"including the {noun}"
        return f"including {'both' if total == 2 else 'all ' + str(total)} {noun}"
    if ok == 0:
        if total == 1:
            return f"and missed the one {noun}"
        return f"and missed {'both' if total == 2 else 'all ' + str(total)} {noun}"
    return f"including {ok} of the {total} {noun}"


def _last_practised(days: int) -> str:
    if days <= 0:
        return "Last practised today."
    if days == 1:
        return "Last practised yesterday."
    return f"Last practised {days} days ago."


def _explain(n: int, correct: int, applied_total: int, applied_ok: int, days: int) -> str:
    """One friendly, specific sentence or two explaining the estimate (text only; no scoring here)."""
    if n < MIN_EVIDENCE:
        more = MIN_EVIDENCE - n
        so_far = "Only 1 answer so far" if n == 1 else f"Only {n} answers so far"
        if n == 1:
            result = " (you got it right)" if correct == 1 else " (not quite right yet)"
        else:
            result = f" ({correct} of {n} right)"
        return f"{so_far}{result}. Answer {more} more and we'll rate this. {_last_practised(days)}"
    head = f"You got {correct} of {n} right"
    if applied_total:
        head += ", " + _applied_clause(applied_total, applied_ok)
    return f"{head}. {_last_practised(days)}"
