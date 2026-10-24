"""Question validation and deterministic grading.

Model-generated questions are validated against a schema before they are
saved (PRD 9.3 "validate before persistence"). Multiple-choice answers are
graded in code. Short and applied answers are graded by the model against a
rubric, but the model's output is also validated and clamped here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .text import jaccard, tokenize

QUESTION_TYPES = ("mcq", "short", "applied")
DIFFICULTIES = ("easy", "medium", "hard")
VERDICTS = ("correct", "partial", "incorrect", "unassessed")


class InvalidQuestion(ValueError):
    pass


@dataclass
class RubricItem:
    criterion: str
    points: int = 1


@dataclass
class QuestionSpec:
    type: str
    prompt: str
    concept: str
    difficulty: str
    explanation: str
    source_labels: list[str]
    options: list[str] = field(default_factory=list)
    correct_index: int | None = None
    answer_key: str = ""
    rubric: list[RubricItem] = field(default_factory=list)


def validate_question(raw: dict, valid_labels: set[str]) -> QuestionSpec:
    qtype = str(raw.get("type", "")).lower().strip()
    if qtype not in QUESTION_TYPES:
        raise InvalidQuestion(f"unknown type {qtype!r}")
    prompt = str(raw.get("prompt", "")).strip()
    if len(prompt) < 10:
        raise InvalidQuestion("prompt too short")
    difficulty = str(raw.get("difficulty", "medium")).lower()
    if difficulty not in DIFFICULTIES:
        difficulty = "medium"
    labels = [str(s).strip("[] ") for s in raw.get("sources", []) if str(s).strip("[] ") in valid_labels]
    if not labels:
        raise InvalidQuestion("no valid source reference")

    spec = QuestionSpec(
        type=qtype,
        prompt=prompt,
        concept=str(raw.get("concept", "")).strip()[:120] or "General",
        difficulty=difficulty,
        explanation=str(raw.get("explanation", "")).strip(),
        source_labels=labels,
    )

    if qtype == "mcq":
        options = [str(o).strip() for o in raw.get("options", []) if str(o).strip()]
        if not 3 <= len(options) <= 5:
            raise InvalidQuestion("mcq needs 3-5 options")
        if len({o.lower() for o in options}) != len(options):
            raise InvalidQuestion("mcq options must be distinct")
        idx = raw.get("correct_index")
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(options):
            raise InvalidQuestion("mcq correct_index out of range")
        spec.options, spec.correct_index = options, idx
        spec.answer_key = options[idx]
    else:
        spec.answer_key = str(raw.get("answer_key", "")).strip()
        if len(spec.answer_key) < 5:
            raise InvalidQuestion("answer_key missing")
        rubric = []
        for item in raw.get("rubric", []):
            if isinstance(item, dict) and str(item.get("criterion", "")).strip():
                pts = item.get("points", 1)
                pts = pts if isinstance(pts, int) and 1 <= pts <= 5 else 1
                rubric.append(RubricItem(str(item["criterion"]).strip(), pts))
            elif isinstance(item, str) and item.strip():
                rubric.append(RubricItem(item.strip(), 1))
        if not rubric:
            raise InvalidQuestion("rubric missing")
        spec.rubric = rubric[:6]
    return spec


def dedupe(specs: list[QuestionSpec], threshold: float = 0.7) -> list[QuestionSpec]:
    kept: list[QuestionSpec] = []
    sigs: list[set[str]] = []
    for s in specs:
        sig = set(tokenize(s.prompt))
        if any(jaccard(sig, other) >= threshold for other in sigs):
            continue
        kept.append(s)
        sigs.append(sig)
    return kept


@dataclass
class Grade:
    verdict: str
    score: float  # 0..1
    feedback: str
    missing: list[str] = field(default_factory=list)
    criteria: list[dict] = field(default_factory=list)


def grade_mcq(correct_index: int, selected: int | None, options: list[str], explanation: str) -> Grade:
    if selected is None:
        return Grade("unassessed", 0.0, "No option selected.")
    if selected == correct_index:
        return Grade("correct", 1.0, explanation or "Correct.")
    right = options[correct_index] if 0 <= correct_index < len(options) else "?"
    return Grade("incorrect", 0.0, f"The correct answer is: {right}. {explanation}".strip())


def normalize_rubric_grade(raw: dict, rubric: list[dict]) -> Grade:
    """Turn a model's rubric judgement into a validated Grade.

    The score is recomputed in code from per-criterion points, so the model
    cannot report a score that disagrees with its own criterion judgements.
    """
    by_name = {}
    for c in raw.get("criteria", []) or []:
        if isinstance(c, dict):
            by_name[str(c.get("criterion", "")).strip().lower()] = c

    total = sum(int(r.get("points", 1)) for r in rubric) or 1
    earned = 0.0
    criteria_out = []
    missing = []
    for r in rubric:
        name = str(r.get("criterion", ""))
        pts = int(r.get("points", 1))
        judged = by_name.get(name.strip().lower())
        status = str(judged.get("status", "missing")).lower() if judged else "missing"
        if status not in ("met", "partial", "missing"):
            status = "missing"
        earned += pts * {"met": 1.0, "partial": 0.5, "missing": 0.0}[status]
        criteria_out.append({
            "criterion": name,
            "points": pts,
            "status": status,
            "evidence": str(judged.get("evidence", "")) if judged else "",
        })
        if status != "met":
            missing.append(name)

    if not by_name:
        return Grade("unassessed", 0.0, str(raw.get("feedback", "Could not evaluate this answer.")), criteria=criteria_out)

    score = round(earned / total, 3)
    verdict = "correct" if score >= 0.85 else "partial" if score >= 0.35 else "incorrect"
    return Grade(verdict, score, str(raw.get("feedback", "")).strip(), missing, criteria_out)
