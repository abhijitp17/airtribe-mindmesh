"""Offline mock for the `plan_topics` task: topics from section headings, deterministic."""
from __future__ import annotations

import re

from .mock import register_mock


def _heading(section: str) -> str:
    last = (section or "").split(" > ")[-1]
    return re.sub(r"^[\d.\s]+", "", last).strip()


@register_mock("plan_topics")
def _plan_topics(ctx: dict) -> dict:
    sources = ctx.get("sources", [])
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for i, s in enumerate(sources, start=1):
        name = _heading(getattr(s, "section", "")) or f"Section {i}"
        if name.casefold() not in {o.casefold() for o in order}:
            order.append(name)
            groups[name] = []
        key = next(o for o in order if o.casefold() == name.casefold())
        groups[key].append(s.label)
    topics = []
    for i, name in enumerate(order[:12]):
        labels = groups[name]
        size = sum(len(s.text) for s in sources if s.label in labels)
        topics.append({
            "topic": name,
            "concept": name[:120],
            "objective": f"Explain {name} and apply it to a new example.",
            "est_minutes": max(15, min(90, 15 + size // 60)),
            "priority": "high" if i < 2 else "medium" if i < 5 else "low",
            "prerequisites": [order[i - 1]] if i > 0 else [],
            "sources": labels,
        })
    return {"topics": topics}
