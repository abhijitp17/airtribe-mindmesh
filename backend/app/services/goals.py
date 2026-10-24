"""Goal planning use cases: topic proposal (model) and plan building (code).

No web or database code here: the router loads rows and passes plain data, so
the whole flow is testable with the mock provider.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Sequence

from ..ai import prompts_goals
from ..ai.gateway import Gateway, Request
from ..core.citations import SourceRef
from ..core.planner import (
    PRIORITY_RANK,
    PlanEntry,
    TopicSpec,
    _attr,
    mock_interview_count,
    plan_warning,
    scale_topics,
    schedule,
    study_dates,
    topics_from_skills,
)
from .learning import ChunkData

log = logging.getLogger("mindmesh.goals")

MAX_SOURCES = 16
MAX_TOPICS = 15


def heading(section: str) -> str:
    last = (section or "").split(" > ")[-1]
    return re.sub(r"^[\d.\s]+", "", last).strip()


def spread_sources(chunks: Sequence[ChunkData], limit: int = MAX_SOURCES) -> list[SourceRef]:
    """One representative chunk per section (document order), thinned evenly to `limit`."""
    substantive = [c for c in chunks if len(c.text.strip()) >= 80] or [c for c in chunks if c.text.strip()]
    picked: list[ChunkData] = []
    seen: set[tuple[str, str]] = set()
    for c in substantive:
        k = (c.document_id, (c.section or "").strip().casefold())
        if k in seen:
            continue
        seen.add(k)
        picked.append(c)
    if len(picked) < min(limit, len(substantive)):
        # Few sections: add more chunks from the material, still in order.
        extra = [c for c in substantive if c not in picked]
        step = max(1, len(extra) // max(1, limit - len(picked)))
        picked += extra[::step][: limit - len(picked)]
        order = {c.id: i for i, c in enumerate(substantive)}
        picked.sort(key=lambda c: order[c.id])
    if len(picked) > limit:
        step = len(picked) / limit
        picked = [picked[int(i * step)] for i in range(limit)]
    return [SourceRef(f"S{i}", c.id, c.text, c.page_start, c.page_end, c.section) for i, c in enumerate(picked, start=1)]


def _require_topics(data: Any) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("topics"), list):
        raise ValueError("reply must be an object with a 'topics' list")
    return data


def clean_topics(raw: Any, sources: Sequence[SourceRef]) -> list[TopicSpec]:
    """Validate model topics: sources must be real labels, minutes clamped, duplicates removed."""
    label_to_chunk = {s.label: s.chunk_id for s in sources}
    items = raw.get("topics", []) if isinstance(raw, dict) else []
    out: list[TopicSpec] = []
    seen: set[str] = set()
    for t in items:
        if not isinstance(t, dict):
            continue
        name = " ".join(str(t.get("topic") or "").split())[:255]
        if not name or name.casefold() in seen:
            continue
        labels = t.get("sources") if isinstance(t.get("sources"), list) else []
        chunk_ids = []
        for label in labels:
            cid = label_to_chunk.get(str(label).strip().strip("[]"))
            if cid and cid not in chunk_ids:
                chunk_ids.append(cid)
        if not chunk_ids:
            log.info("dropped topic without a valid source: %s", name[:60])
            continue
        try:
            minutes = int(round(float(t.get("est_minutes", 30))))
        except (TypeError, ValueError):
            minutes = 30
        minutes = max(10, min(180, minutes))
        prereqs_raw = t.get("prerequisites") if isinstance(t.get("prerequisites"), list) else []
        prereqs = []
        for p in prereqs_raw:
            p = " ".join(str(p).split())
            match = next((o.topic for o in out if o.topic.casefold() == p.casefold()), None)
            if match and match not in prereqs:
                prereqs.append(match)  # only earlier topics; prevents cycles and forward refs
        concept = " ".join(str(t.get("concept") or name).split())[:120] or name[:120]
        seen.add(name.casefold())
        out.append(TopicSpec(
            topic=name, concept=concept, est_minutes=minutes,
            priority=PRIORITY_RANK.get(str(t.get("priority", "medium")).lower(), 2),
            prerequisites=prereqs, source_chunk_ids=chunk_ids, activity="learn",
            objective=" ".join(str(t.get("objective") or "").split())[:500],
        ))
        if len(out) >= MAX_TOPICS:
            break
    return out


def topics_from_headings(sources: Sequence[SourceRef]) -> list[TopicSpec]:
    """Fallback when the model returns nothing usable: one topic per section heading."""
    out: list[TopicSpec] = []
    for s in sources:
        name = heading(s.section) or f"Pages {s.page_start}-{s.page_end}"
        existing = next((t for t in out if t.topic.casefold() == name.casefold()), None)
        if existing:
            existing.source_chunk_ids.append(s.chunk_id)
            continue
        out.append(TopicSpec(
            topic=name[:255], concept=name[:120], est_minutes=30, priority=2,
            prerequisites=[out[-1].topic] if out else [], source_chunk_ids=[s.chunk_id],
            objective=f"Explain {name} in your own words.",
        ))
    return out[:MAX_TOPICS]


def propose_topics(
    gw: Gateway, chunks: Sequence[ChunkData], goal_type: str, title: str, outcome: str,
    level: str, deadline: date, minutes_per_day: int,
) -> list[TopicSpec]:
    sources = spread_sources(chunks)
    if not sources:
        return []
    try:
        data = _request_topics(gw, sources, goal_type, title, outcome, level, deadline, minutes_per_day)
    except (ValueError, KeyError, TypeError) as exc:  # unusable JSON even after the repair attempt
        log.info("plan_topics reply unusable (%s); falling back to section headings", type(exc).__name__)
        return topics_from_headings(sources)
    topics = clean_topics(data, sources)
    return topics or topics_from_headings(sources)


def _request_topics(gw: Gateway, sources: list[SourceRef], goal_type: str, title: str, outcome: str,
                    level: str, deadline: date, minutes_per_day: int) -> dict:
    return gw.complete_json(
        Request(
            task="plan_topics",
            system=prompts_goals.PLAN_TOPICS_SYSTEM,
            user=prompts_goals.plan_topics_user(goal_type, title, outcome, level, deadline.isoformat(), minutes_per_day, sources),
            tier="main",
            max_tokens=2500,
            temperature=0.2,
            context={"sources": sources, "goal_type": goal_type, "title": title, "level": level},
        ),
        validate=_require_topics,
    )


def adjust_for_goal(topics: Sequence[TopicSpec], goal_type: str, level: str) -> list[TopicSpec]:
    out = scale_topics(topics, level)
    if goal_type == "revise":
        for t in out:
            if t.activity == "learn":
                t.activity = "practice"
                t.est_minutes = max(10, int(round(t.est_minutes * 0.6)))
    return out


def build_plan(
    *, today: date, goal_type: str, deadline: date, minutes_per_day: int, study_days: Sequence[int],
    level: str, topics: Sequence[TopicSpec], fixed: Sequence[PlanEntry] = (), interview: bool = False,
    scale: bool = True,
) -> tuple[list[PlanEntry], str | None, list[TopicSpec]]:
    """Schedule topics. Returns (entries incl. fixed, warning, topics that were left out)."""
    mocks = mock_interview_count(today, deadline, study_days) if interview else 0
    specs = adjust_for_goal(topics, goal_type, level) if scale else list(topics)
    entries, warning = schedule(today, deadline, minutes_per_day, study_days, specs, fixed, mocks)
    kept = {_k(e.topic) for e in entries}
    dropped = [t for t in specs if _k(t.topic) not in kept]
    return entries, warning, dropped


# ---------- topics that didn't fit (persisted as visible "left out" rows) ----------

# The goal table has no column for the planner's warning, so topics that didn't
# fit are stored as `skipped` plan items with this reason prefix. They're shown
# to the user, excluded from stats and budgets, and rebuilt on every replan.
DROPPED_PREFIX = "Left out:"


def _k(s: str | None) -> str:
    return " ".join((s or "").split()).casefold()


def dropped_reason(minutes_per_day: int, deadline: date) -> str:
    return (f"{DROPPED_PREFIX} this didn't fit in {minutes_per_day} min/day before {deadline.isoformat()}. "
            "Mark it pending to add it anyway, or change your budget or deadline and regenerate.")


def is_dropped(item: Any) -> bool:
    return _attr(item, "status") == "skipped" and str(_attr(item, "reason") or "").startswith(DROPPED_PREFIX)


def goal_warning(items: Sequence[Any], today: date, deadline: date, minutes_per_day: int, study_days: Sequence[int]) -> str | None:
    """Feasibility warning derived from stored rows, so it survives reloads."""
    msgs = []
    dropped = [str(_attr(i, "topic")) for i in items if is_dropped(i)]
    if dropped:
        msgs.append(
            f"Not everything fits in {minutes_per_day} min/day on your study days before {deadline.isoformat()}. "
            f"Left out (lowest priority first): {', '.join(dropped)}. "
            "Add study days, raise your daily minutes or move the deadline to include them."
        )
    pending = [i for i in items if _attr(i, "status") == "pending"]
    if pending and not study_dates(today, deadline, study_days):
        msgs.append("There are no study days left before your deadline.")
    w = plan_warning([i for i in items if not is_dropped(i)], today, deadline, minutes_per_day)
    if w:
        msgs.append(w)
    return " ".join(msgs) or None


CORE_ORDER = ("learn", "drill", "practice")


def topics_from_items(items: Sequence[Any]) -> list[TopicSpec]:
    """Rebuild topic specs from stored items (for schedule-only replans, no model call).

    Minutes are already level-adjusted, so pass ``scale=False`` to build_plan.
    """
    rows = sorted(items, key=lambda i: _attr(i, "position"))
    groups: dict[str, list[Any]] = {}
    for i in rows:
        if _attr(i, "activity_type") == "mock_interview":
            continue
        groups.setdefault(_k(_attr(i, "topic")), []).append(i)
    out: list[TopicSpec] = []
    for rows_t in groups.values():
        acts = {_attr(i, "activity_type") for i in rows_t}
        core = next((a for a in CORE_ORDER if a in acts), None)
        if core is None:
            continue  # review-only topic (e.g. added by adapt)
        if all(_attr(i, "user_edited") and not (_attr(i, "source_chunk_ids") or []) for i in rows_t):
            continue  # the user's own sessions: kept as fixed items, nothing generated around them
        core_rows = [i for i in rows_t if _attr(i, "activity_type") == core]
        first = core_rows[0]
        chunk_ids: list[str] = []
        for i in core_rows:
            for c in _attr(i, "source_chunk_ids") or []:
                if c not in chunk_ids:
                    chunk_ids.append(c)
        objective = re.sub(r"\s*\(part \d+ of \d+\)$", "", str(_attr(first, "objective") or ""))
        out.append(TopicSpec(
            topic=str(_attr(first, "topic")), concept=_attr(first, "concept"),
            est_minutes=max(10, min(480, sum(int(_attr(i, "estimated_minutes")) for i in core_rows))),
            priority=1 if all(is_dropped(i) for i in core_rows) else 2,
            prerequisites=[out[-1].topic] if out else [], source_chunk_ids=chunk_ids,
            activity=core, objective=objective,
        ))
    return out


__all__ = [
    "DROPPED_PREFIX", "adjust_for_goal", "build_plan", "clean_topics", "dropped_reason", "goal_warning",
    "is_dropped", "propose_topics", "spread_sources", "topics_from_headings", "topics_from_items", "topics_from_skills",
]
