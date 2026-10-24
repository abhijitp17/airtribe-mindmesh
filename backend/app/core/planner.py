"""Deterministic study planner (PRD FR-020..023, CONTRACTS §4).

The model proposes *what* to study (ordered topics with prerequisites and an
effort estimate). This module decides *when*, with hard guarantees:

* the minutes scheduled on a day never exceed ``minutes_per_day`` (fixed,
  user-edited items count against the budget and are never moved);
* nothing is scheduled after the deadline;
* a topic never starts before its prerequisites have been learned;
* large topics are split into sessions that fit the daily budget;
* spaced ``review`` sessions follow practice at +1/+3/+7 days when there is
  capacity left (they never displace core sessions);
* if the core sessions don't fit, the lowest-priority topic is dropped and a
  feasibility warning names it. Sessions are never compressed silently;
* interview goals get ``mock_interview`` sessions in the final study days.

``adapt`` turns missed sessions and weak mastery into a *proposal* (the user
accepts or rejects it). ``compute_stats`` and ``plan_warning`` summarise a plan.

No FastAPI, SQLAlchemy or I/O here: everything is plain data so it can be
tested exhaustively.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

ACTIVITIES = ("learn", "practice", "review", "mock_interview", "drill")
PRIORITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

MIN_SESSION = 10       # minutes; shortest session we create when splitting
MAX_SESSION = 90       # minutes; longest single sitting we create
REVIEW_MINUTES = 15
MOCK_MINUTES = 45
REVIEW_OFFSETS = (1, 3, 7)
REVIEW_SLACK_DAYS = 2  # a review may slide this many days later, never earlier
LEVEL_FACTOR = {"beginner": 1.25, "standard": 1.0, "advanced": 0.8}


@dataclass
class TopicSpec:
    topic: str
    concept: str | None = None
    est_minutes: int = 30
    priority: int = 2  # higher = more important (critical 4 .. low 1)
    prerequisites: list[str] = field(default_factory=list)  # topic names
    source_chunk_ids: list[str] = field(default_factory=list)
    activity: str = "learn"  # learn | practice | drill
    objective: str = ""


@dataclass
class PlanEntry:
    scheduled_date: date
    topic: str
    activity_type: str
    estimated_minutes: int
    concept: str | None = None
    objective: str = ""
    source_chunk_ids: list[str] = field(default_factory=list)
    reason: str = ""
    status: str = "pending"
    fixed: bool = False      # existing row kept in place (user-edited or history)
    id: str | None = None    # row id for fixed entries
    position: int = 0
    user_edited: bool = False  # a fixed, user-edited entry covers its whole topic/activity


def _key(s: str | None) -> str:
    return " ".join((s or "").split()).casefold()


def study_dates(start: date, end: date, study_days: Iterable[int]) -> list[date]:
    days = {int(d) for d in study_days if 0 <= int(d) <= 6}
    if end < start or not days:
        return []
    out, d = [], start
    while d <= end:
        if d.weekday() in days:
            out.append(d)
        d += timedelta(days=1)
    return out


def scale_topics(topics: Sequence[TopicSpec], level: str) -> list[TopicSpec]:
    """Adjust effort for the learner's level, keeping minutes in 10..180."""
    f = LEVEL_FACTOR.get(level, 1.0)
    out = []
    for t in topics:
        out.append(TopicSpec(
            t.topic, t.concept, max(10, min(180, int(round(t.est_minutes * f)))), t.priority,
            list(t.prerequisites), list(t.source_chunk_ids), t.activity, t.objective,
        ))
    return out


def topological_order(topics: Sequence[TopicSpec]) -> list[TopicSpec]:
    """Stable topological sort: keep the proposed order unless a prerequisite forces otherwise.

    Unknown prerequisites are ignored; cycles are broken at the earliest remaining topic.
    """
    index = {_key(t.topic): i for i, t in enumerate(topics)}
    deps = [{index[_key(p)] for p in t.prerequisites if _key(p) in index and index[_key(p)] != i} for i, t in enumerate(topics)]
    done: set[int] = set()
    order: list[int] = []
    remaining = list(range(len(topics)))
    while remaining:
        pick = next((i for i in remaining if deps[i] <= done), remaining[0])
        remaining.remove(pick)
        done.add(pick)
        order.append(pick)
    return [topics[i] for i in order]


def practice_minutes(est: int, budget: int) -> int:
    return min(budget, max(10, min(25, int(round(est * 0.25)))))


class _Calendar:
    def __init__(self, days: list[date], budget: int, fixed: Sequence[PlanEntry]):
        self.days = days
        self.budget = budget
        self.cap = {d: budget for d in days}
        for f in fixed:
            if f.scheduled_date in self.cap and f.status != "skipped":
                self.cap[f.scheduled_date] = max(0, self.cap[f.scheduled_date] - f.estimated_minutes)

    def first_index(self, earliest: date) -> int:
        for i, d in enumerate(self.days):
            if d >= earliest:
                return i
        return len(self.days)

    def find(self, earliest: date, minutes: int, latest: date | None = None) -> date | None:
        for d in self.days[self.first_index(earliest):]:
            if latest is not None and d > latest:
                return None
            if self.cap[d] >= minutes:
                return d
        return None

    def take(self, d: date, minutes: int) -> None:
        assert self.cap[d] >= minutes, "planner bug: budget exceeded"
        self.cap[d] -= minutes

    def split(self, earliest: date, minutes: int) -> list[tuple[date, int]] | None:
        """Place `minutes` across consecutive days with capacity; None if it doesn't fit."""
        max_session = min(self.budget, MAX_SESSION)
        parts: list[tuple[date, int]] = []
        remaining = minutes
        i = self.first_index(earliest)
        while remaining > 0:
            need = min(remaining, MIN_SESSION)
            while i < len(self.days) and self.cap[self.days[i]] < need:
                i += 1
            if i >= len(self.days):
                return None
            d = self.days[i]
            chunk = min(remaining, self.cap[d], max_session)
            rest = remaining - chunk
            if 0 < rest < MIN_SESSION and chunk - (MIN_SESSION - rest) >= MIN_SESSION:
                chunk -= MIN_SESSION - rest  # avoid a tiny trailing session
            self.take(d, chunk)
            parts.append((d, chunk))
            remaining -= chunk
            i += 1
        return parts


def _mock_entries(cal: _Calendar, count: int, fixed: Sequence[PlanEntry]) -> list[PlanEntry]:
    count -= sum(1 for f in fixed if f.activity_type == "mock_interview")
    out: list[PlanEntry] = []
    floor = min(20, cal.budget)
    for d in reversed(cal.days):
        if len(out) >= count:
            break
        if cal.cap[d] >= floor:
            m = min(MOCK_MINUTES, cal.cap[d])
            cal.take(d, m)
            n = count - len(out)
            out.append(PlanEntry(
                d, "Mock interview", "mock_interview", m,
                objective="Answer realistic interview questions out loud and review the feedback.",
                reason=f"Scheduled in the final days before your deadline ({n} of {count} remaining) to rehearse under realistic conditions.",
            ))
    out.reverse()
    return out


def _try_schedule(
    days: list[date], budget: int, topics: list[TopicSpec], fixed: Sequence[PlanEntry], mock_count: int,
) -> tuple[list[PlanEntry], int | None]:
    """One greedy pass. Returns (entries, None) or (partial, index of topic that didn't fit)."""
    cal = _Calendar(days, budget, fixed)
    mocks = _mock_entries(cal, mock_count, fixed)
    start = days[0] if days else date.max

    # What fixed entries already cover. A user-edited entry covers its topic/activity
    # completely (the user decided); kept history (e.g. a done "part 1 of 3") covers
    # only its own minutes, so the rest of the topic is still scheduled.
    covered: dict[tuple[str, str], date] = {}
    covered_min: dict[tuple[str, str], int] = {}
    covered_hard: set[tuple[str, str]] = set()
    for f in fixed:
        k = (_key(f.topic), f.activity_type)
        covered[k] = max(covered.get(k, f.scheduled_date), f.scheduled_date)
        covered_min[k] = covered_min.get(k, 0) + f.estimated_minutes
        if f.user_edited:
            covered_hard.add(k)

    entries: list[PlanEntry] = []
    finish: dict[str, date] = {}
    practice_day: dict[int, date] = {}
    cursor = start
    for ti, t in enumerate(topics):
        tk = _key(t.topic)
        concept = t.concept or t.topic
        prereq_names = [p for p in t.prerequisites if _key(p) in finish]
        earliest = max([cursor] + [finish[_key(p)] for p in prereq_names])
        core_act = t.activity if t.activity in ("learn", "practice", "drill") else "learn"

        ck = (tk, core_act)
        todo = t.est_minutes - covered_min.get(ck, 0)
        if ck in covered and (ck in covered_hard or todo < MIN_SESSION):
            last = covered[ck]
        else:
            parts = cal.split(max(earliest, covered.get(ck, earliest)), todo)
            if parts is None:
                return entries, ti
            if prereq_names:
                why = f"Comes after {', '.join(prereq_names)}, which it builds on."
            else:
                why = f"Step {ti + 1} of your plan, in the order that builds understanding."
            for pi, (d, m) in enumerate(parts):
                label = f" (part {pi + 1} of {len(parts)})" if len(parts) > 1 else ""
                entries.append(PlanEntry(
                    d, t.topic, core_act, m, concept=concept,
                    objective=(t.objective or f"Work through {t.topic}.") + label,
                    source_chunk_ids=list(t.source_chunk_ids),
                    reason=why + (" Split so no day goes over your budget." if len(parts) > 1 else ""),
                ))
            last = parts[-1][0]
            cursor = last
        finish[tk] = last

        check_day = last
        if core_act == "learn":
            if (tk, "practice") in covered:
                check_day = covered[(tk, "practice")]
            else:
                pm = practice_minutes(t.est_minutes, budget)
                d = cal.find(last, pm)
                if d is None:
                    return entries, ti
                cal.take(d, pm)
                entries.append(PlanEntry(
                    d, t.topic, "practice", pm, concept=concept,
                    objective=f"Test yourself on {t.topic} with a short quiz from your documents.",
                    source_chunk_ids=list(t.source_chunk_ids),
                    reason="Practice right after learning shows what stuck and feeds your mastery estimate.",
                ))
                check_day = d
        if (tk, "review") not in covered:
            practice_day[ti] = check_day

    # Spaced reviews only use leftover capacity, so they never cause a drop.
    rm = min(REVIEW_MINUTES, budget)
    for ti, base in practice_day.items():
        t = topics[ti]
        prev = base
        for off in REVIEW_OFFSETS:
            target = max(base + timedelta(days=off), prev + timedelta(days=1))
            d = cal.find(target, rm, latest=target + timedelta(days=REVIEW_SLACK_DAYS))
            if d is None:
                continue
            cal.take(d, rm)
            prev = d
            entries.append(PlanEntry(
                d, t.topic, "review", rm, concept=t.concept or t.topic,
                objective=f"Quick recall check on {t.topic}.",
                source_chunk_ids=list(t.source_chunk_ids),
                reason=f"Spaced review {(d - base).days} day(s) after practice, so it moves into long-term memory.",
            ))
    return entries + mocks, None


def schedule(
    start_date: date,
    deadline: date,
    minutes_per_day: int,
    study_days: Iterable[int],
    topics: Sequence[TopicSpec],
    fixed_items: Sequence[PlanEntry] = (),
    mock_interviews: int = 0,
) -> tuple[list[PlanEntry], str | None]:
    """Build a plan. Returns (all entries incl. fixed, sorted with positions, feasibility warning)."""
    budget = max(1, int(minutes_per_day))
    days = study_dates(start_date, deadline, study_days)
    fixed = [PlanEntry(**{**f.__dict__, "fixed": True}) for f in fixed_items]
    ordered = topological_order(list(topics))
    dropped: list[str] = []
    warning: str | None = None

    if not days:
        dropped = [t.topic for t in ordered]
        entries: list[PlanEntry] = []
        if ordered or mock_interviews:
            warning = (
                "There are no study days between today and your deadline, so nothing could be scheduled. "
                "Move the deadline or add study days."
                + (f" Left out: {', '.join(dropped)}." if dropped else "")
            )
    else:
        active = list(ordered)
        while True:
            entries, failed = _try_schedule(days, budget, active, fixed, mock_interviews)
            if failed is None:
                break
            # Drop the lowest-priority topic (ties: the latest one) and retry from scratch.
            victim = min(range(len(active)), key=lambda i: (active[i].priority, -i))
            dropped.append(active[victim].topic)
            del active[victim]
        if dropped:
            warning = (
                f"Not everything fits in {budget} min/day on your study days before {deadline.isoformat()}. "
                f"Left out (lowest priority first): {', '.join(dropped)}. "
                "Add study days, raise your daily minutes or move the deadline to include them."
            )

    def sort_key(e: tuple[int, PlanEntry]) -> tuple:
        i, p = e
        group = 0 if p.fixed else (2 if p.activity_type == "mock_interview" else 1)
        return (p.scheduled_date, group, p.position if p.fixed else i)

    allp = [(i, p) for i, p in enumerate(fixed)] + [(i, p) for i, p in enumerate(entries)]
    result = [p for _, p in sorted(allp, key=sort_key)]
    for pos, p in enumerate(result):
        p.position = pos
    return result, warning


def mock_interview_count(start: date, deadline: date, study_days: Iterable[int]) -> int:
    n = len(study_dates(start, deadline, study_days))
    return 0 if n == 0 else 1 if n < 6 else 2 if n < 20 else 3


# ---------- interview topics ----------

GAP_ACTIVITY = {
    "knowledge_gap": ("learn", 60),
    "stretch": ("learn", 45),
    "application_gap": ("practice", 45),
    "unverified": ("practice", 30),
    "evidence_gap": ("drill", 30),
    "communication_gap": ("drill", 30),
}


def topics_from_skills(skills: Sequence[dict[str, Any]]) -> list[TopicSpec]:
    """Seed interview topics from prep skill gaps: critical/high first, strong skills skipped."""
    rows = []
    for i, s in enumerate(skills):
        gap = s.get("gap_type") or "unverified"
        if gap == "strong":
            continue
        override = s.get("user_override") or {}
        prio = (override.get("priority") if isinstance(override, dict) else None) or s.get("priority") or "medium"
        rank = PRIORITY_RANK.get(prio, 2)
        act, minutes = GAP_ACTIVITY.get(gap, ("practice", 30))
        name = str(s.get("name") or "").strip()[:255]
        if not name:
            continue
        rows.append((-rank, i, TopicSpec(
            topic=name, concept=name[:120], est_minutes=minutes, priority=rank,
            source_chunk_ids=[str(c) for c in (s.get("linked_chunk_ids") or [])],
            activity=act, objective=str(s.get("recommended_action") or "")[:500],
        )))
    rows.sort(key=lambda r: (r[0], r[1]))
    seen, out = set(), []
    for _, _, t in rows:
        if _key(t.topic) not in seen:
            seen.add(_key(t.topic))
            out.append(t)
    return out


# ---------- stats, warnings ----------

def _attr(o: Any, name: str) -> Any:
    return o[name] if isinstance(o, dict) else getattr(o, name)


def compute_stats(items: Sequence[Any], today: date, deadline: date, minutes_per_day: int, study_days: Iterable[int]) -> dict:
    counted = [i for i in items if _attr(i, "status") != "skipped"]
    done = [i for i in counted if _attr(i, "status") == "done"]
    pending = [i for i in counted if _attr(i, "status") == "pending"]
    capacity = minutes_per_day * len(study_dates(today, deadline, study_days))
    overdue = any(_attr(i, "scheduled_date") < today for i in pending)
    remaining = sum(_attr(i, "estimated_minutes") for i in pending)
    return {
        "total_minutes": sum(_attr(i, "estimated_minutes") for i in counted),
        "done_minutes": sum(_attr(i, "estimated_minutes") for i in done),
        "items_done": len(done),
        "items_total": len(counted),
        "on_track": (not overdue) and remaining <= capacity,
        "days_left": max(0, (deadline - today).days),
        "capacity_minutes": capacity,
    }


def plan_warning(items: Sequence[Any], today: date, deadline: date, minutes_per_day: int) -> str | None:
    """Problems visible in the stored plan (usually from manual edits)."""
    load: dict[date, int] = {}
    late = 0
    for i in items:
        if _attr(i, "status") == "skipped":
            continue
        d = _attr(i, "scheduled_date")
        if d >= today:
            load[d] = load.get(d, 0) + _attr(i, "estimated_minutes")
        if d > deadline and _attr(i, "status") == "pending":
            late += 1
    over = sorted(d for d, m in load.items() if m > minutes_per_day)
    msgs = []
    if over:
        msgs.append(f"{len(over)} day(s) add up to more than your {minutes_per_day}-minute budget (first: {over[0].isoformat()}).")
    if late:
        msgs.append(f"{late} session(s) are after your deadline.")
    return " ".join(msgs) or None


# ---------- adaptation ----------

@dataclass
class AdaptResult:
    reason: str
    changes: list[dict]


def adapt(
    items: Sequence[Any],
    today: date,
    deadline: date,
    minutes_per_day: int,
    study_days: Iterable[int],
    mastery_by_concept: dict[str, str] | None = None,
) -> AdaptResult | None:
    """Propose changes for missed sessions and weak concepts. None when the plan is fine."""
    mastery = {_key(k): v for k, v in (mastery_by_concept or {}).items()}
    days = study_dates(today, deadline, study_days)
    load = {d: 0 for d in days}
    for i in items:
        d = _attr(i, "scheduled_date")
        if d in load and _attr(i, "status") != "skipped":
            load[d] += _attr(i, "estimated_minutes")

    def free_day(minutes: int, earliest: date = today) -> date | None:
        for d in days:
            if d >= earliest and minutes_per_day - load[d] >= minutes:
                return d
        return None

    changes: list[dict] = []
    missed = sorted(
        (i for i in items if _attr(i, "status") == "pending" and _attr(i, "scheduled_date") < today),
        key=lambda i: (_attr(i, "scheduled_date"), _attr(i, "position")),
    )
    for i in missed:
        m = _attr(i, "estimated_minutes")
        was = _attr(i, "scheduled_date").isoformat()
        d = free_day(m)
        if d is not None:
            load[d] += m
            changes.append({
                "op": "move", "item_id": _attr(i, "id"), "topic": _attr(i, "topic"),
                "activity_type": _attr(i, "activity_type"), "to_date": d.isoformat(), "minutes": m,
                "why": f"Missed on {was}. Moved to the first study day with {m} free minutes in your daily budget.",
            })
        else:
            changes.append({
                "op": "remove", "item_id": _attr(i, "id"), "topic": _attr(i, "topic"),
                "activity_type": _attr(i, "activity_type"),
                "why": f"Missed on {was}, and no study day before the deadline has {m} free minutes. "
                       "Remove it, or reject this and raise your daily minutes or move the deadline.",
            })

    weak: list[str] = []
    rm = min(REVIEW_MINUTES, minutes_per_day)
    seen: set[str] = set()
    for i in sorted(items, key=lambda i: (_attr(i, "scheduled_date"), _attr(i, "position"))):
        if _attr(i, "activity_type") == "mock_interview":
            continue
        name = _attr(i, "concept") or _attr(i, "topic")
        k = _key(name)
        if not k or k in seen:
            continue
        seen.add(k)
        level = mastery.get(k) or mastery.get(_key(_attr(i, "topic")))
        if level != "weak":
            continue
        soon = today + timedelta(days=3)
        has_soon = any(
            _key(_attr(j, "concept") or _attr(j, "topic")) == k and _attr(j, "status") == "pending"
            and _attr(j, "activity_type") in ("review", "practice") and today <= _attr(j, "scheduled_date") <= soon
            for j in items
        )
        if has_soon:
            continue
        d = free_day(rm)
        if d is None:
            continue
        load[d] += rm
        weak.append(name)
        changes.append({
            "op": "add", "item_id": None, "topic": name, "activity_type": "review",
            "to_date": d.isoformat(), "minutes": rm,
            "why": f"Your recent answers show {name} needs more work, so a short review is added before it slips further.",
        })

    if not changes:
        return None
    n_missed = len(missed)
    parts = []
    if n_missed:
        parts.append(f"You missed {n_missed} session(s)")
    if weak:
        parts.append(f"{len(weak)} concept(s) need more work ({', '.join(weak[:3])})")
    reason = " and ".join(parts) + ". Here is a suggested update that stays within your daily budget and deadline."
    return AdaptResult(reason, changes)
