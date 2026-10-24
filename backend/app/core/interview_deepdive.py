"""Resume deep-dive questions (PRD §7.4).

Interviewers probe the claims on a resume: "improved forecast accuracy by 8%"
will draw questions about how accuracy was defined, the baseline, the period,
the method and what else could explain the change. These templates are
deterministic so every metric or claim gets the right probes even offline;
the model may add bullet-specific questions on top, but never replaces these.

Templates only ever restate the candidate's own words; they never assume
facts that are not in the bullet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_QUESTIONS_PER_BULLET = 6

_METRIC_RE = re.compile(
    r"(?:\bfrom\s+[$€£₹]?\d[\d,.]*\s?\w*\s+to\s+[$€£₹]?\d[\d,.]*\s?\w*"
    r"|[$€£₹]\s?\d[\d,.]*\s?(?:[kmb]|bn|million|billion|thousand)?\b"
    r"|\d[\d,.]*\s?(?:%|percent|pp\b|x\b|×)"
    r"|\b\d[\d,.]*\+?\s?(?:users|customers|clients|people|engineers|reports|stores|markets|countries|teams|projects|hours|days|weeks|months|ms|seconds|minutes|requests|transactions|accounts|sku?s)\b)",
    re.I,
)
_CHANGE_RE = re.compile(r"\b(improv|increas|reduc|decreas|cut|grew|grow|boost|rais|lower|sav|accelerat|shorten|doubl|tripl|halv)\w*", re.I)
# Past-tense verbs only: "dashboard design" or "lead time" are nouns, not claims.
_LEAD_RE = re.compile(r"\b(led|managed|owned|headed|spearheaded|directed|mentored|supervised|coached)\b", re.I)
_BUILD_RE = re.compile(r"\b(built|designed|developed|implemented|architected|created|launched|automated|deployed|migrated)\b", re.I)


@dataclass(frozen=True)
class Claim:
    metric: str | None
    is_change: bool
    is_leadership: bool
    is_build: bool

    @property
    def probeable(self) -> bool:
        return bool(self.metric) or self.is_leadership or self.is_build


def analyse_claim(bullet: str) -> Claim:
    m = _METRIC_RE.search(bullet)
    return Claim(
        metric=m.group(0).strip() if m else None,
        is_change=bool(_CHANGE_RE.search(bullet)),
        is_leadership=bool(_LEAD_RE.search(bullet)),
        is_build=bool(_BUILD_RE.search(bullet)),
    )


def _metric_questions(metric: str, is_change: bool) -> list[str]:
    qs = [f"You mention \"{metric}\". How exactly was that measured, and what was the definition of the metric?"]
    if is_change:
        qs += [
            "What was the baseline before your work, and over what period did you measure the change?",
            "What method or approach produced the improvement, and why did you choose it over alternatives?",
            "How do you know the change came from your work and not from other factors (seasonality, other teams, market shifts)?",
        ]
    else:
        qs.append("What made that number hard to reach, and how did it compare with expectations?")
    return qs


def template_questions(bullet: str) -> list[str]:
    """Deterministic probes for one bullet; empty when there is nothing specific to probe."""
    claim = analyse_claim(bullet)
    qs: list[str] = []
    if claim.metric:
        qs += _metric_questions(claim.metric, claim.is_change)
    if claim.is_leadership:
        qs.append("What was your personal role versus the team's? Which decisions were yours, and how many people were involved?")
    if claim.is_build:
        qs.append("Walk me through the design. What trade-offs did you make, and what would you change with hindsight?")
    if claim.probeable:
        qs.append("What went wrong or was harder than expected, and how did you handle it?")
    return qs[:MAX_QUESTIONS_PER_BULLET]


def merge_questions(templates: list[str], generated: list[str]) -> list[str]:
    """Templates first (guaranteed coverage), then unique model questions up to the cap."""
    out, seen = [], set()
    for q in templates + generated:
        key = re.sub(r"\W+", " ", q.lower()).strip()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
    return out[:MAX_QUESTIONS_PER_BULLET]
