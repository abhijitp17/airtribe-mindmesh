"""Offline concept extraction: section names (or the first words of an excerpt) with a verbatim quote."""
from __future__ import annotations

from .mock import register_mock


@register_mock("concept_extract")
def _concept_extract(ctx: dict) -> dict:
    out, seen = [], set()
    for s in ctx.get("sources", []):
        words = s.text.split()
        if len(words) < 6:
            continue
        name = s.section.split(" > ")[-1].strip() if s.section else " ".join(words[:3])
        name = " ".join(w for w in name.split() if not w.isdigit() and w.lower() not in ("chapter", "section"))
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        out.append({"name": name[:60], "source": s.label, "quote": " ".join(words[:10])})
    out = out[:12]
    # Offline prerequisites: each concept builds on the one before it, quoting the later excerpt.
    by_label = {s.label: s for s in ctx.get("sources", [])}
    prereqs = [{"before": a["name"], "after": b["name"], "source": b["source"],
                "quote": " ".join(by_label[b["source"]].text.split()[:12])}
               for a, b in zip(out, out[1:])]
    return {"concepts": out, "prerequisites": prereqs}
