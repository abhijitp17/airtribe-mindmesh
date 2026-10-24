"""Gold-set and quiz-config loading with strict validation.

A malformed gold case fails loudly with its line number, because a silently
skipped case would make the eval look better than it is.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

EXPECT_VALUES = ("answer", "not_found")
LEVELS = ("beginner", "standard", "advanced")


class GoldSetError(ValueError):
    pass


@dataclass(frozen=True)
class GoldCase:
    id: str
    doc: str  # path relative to evals/, e.g. "docs/operations.txt"
    question: str
    expect: str  # "answer" | "not_found"
    must_cite_pages: tuple[int, ...]
    key_facts: tuple[str, ...]
    level: str = "standard"
    must_not_contain: tuple[str, ...] = ()  # canaries an answer must never include (prompt-injection cases)


@dataclass(frozen=True)
class QuizSpec:
    doc: str
    focus: str | None


@dataclass(frozen=True)
class QuizConfig:
    count: int
    difficulty: str
    runs: tuple[QuizSpec, ...]


def parse_case(raw: object, where: str) -> GoldCase:
    """Validate one decoded JSONL object and turn it into a GoldCase."""
    if not isinstance(raw, dict):
        raise GoldSetError(f"{where}: expected an object")
    if "TODO" in json.dumps(raw):
        raise GoldSetError(f"{where}: still has TODO placeholders (fill in the draft from evals.make_gold)")
    for key in ("id", "doc", "question", "expect"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise GoldSetError(f"{where}: '{key}' must be a non-empty string")
    expect = raw["expect"]
    if expect not in EXPECT_VALUES:
        raise GoldSetError(f"{where}: 'expect' must be one of {EXPECT_VALUES}")
    pages = raw.get("must_cite_pages", [])
    if not isinstance(pages, list) or not all(isinstance(p, int) and not isinstance(p, bool) and p >= 1 for p in pages):
        raise GoldSetError(f"{where}: 'must_cite_pages' must be a list of page numbers >= 1")
    facts = raw.get("key_facts", [])
    if not isinstance(facts, list) or not all(isinstance(f, str) and f.strip() for f in facts):
        raise GoldSetError(f"{where}: 'key_facts' must be a list of non-empty strings")
    if expect == "answer" and not pages:
        raise GoldSetError(f"{where}: answerable cases need at least one must_cite_page")
    if expect == "not_found" and (pages or facts):
        raise GoldSetError(f"{where}: not_found cases must have empty must_cite_pages and key_facts")
    level = raw.get("level", "standard")
    if level not in LEVELS:
        raise GoldSetError(f"{where}: 'level' must be one of {LEVELS}")
    banned = raw.get("must_not_contain", [])
    if not isinstance(banned, list) or not all(isinstance(b, str) and b.strip() for b in banned):
        raise GoldSetError(f"{where}: 'must_not_contain' must be a list of non-empty strings")
    return GoldCase(raw["id"], raw["doc"], raw["question"].strip(), expect, tuple(pages), tuple(facts), level,
                    tuple(banned))


def load_gold(path: Path) -> list[GoldCase]:
    """Read a JSONL gold set. Blank lines are allowed; ids must be unique."""
    cases: list[GoldCase] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path.name}:{lineno}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GoldSetError(f"{where}: invalid JSON ({exc.msg})") from exc
        case = parse_case(raw, where)
        if case.id in seen:
            raise GoldSetError(f"{where}: duplicate id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
    return cases


def load_quiz_config(path: Path) -> QuizConfig:
    """Read the quiz-eval config: one generate_quiz run per (doc, focus)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    count = raw.get("count", 5)
    if not isinstance(count, int) or not 1 <= count <= 15:
        raise GoldSetError(f"{path.name}: 'count' must be an integer from 1 to 15")
    runs = tuple(
        QuizSpec(entry["doc"], focus)
        for entry in raw.get("docs", [])
        for focus in entry.get("focus", [None])
    )
    if not runs:
        raise GoldSetError(f"{path.name}: no quiz runs configured")
    return QuizConfig(count, str(raw.get("difficulty", "medium")), runs)
