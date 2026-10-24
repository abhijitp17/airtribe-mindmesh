"""Draft a gold set for one of your own PDFs, for a human to finish.

    python -m evals.make_gold private/pdfs/textbook.pdf > evals/private/textbook.jsonl

Writes one answerable case per section (with the section's real pages filled in) plus two
off-topic "not_found" cases. Every question and key fact starts as TODO and the loader refuses
to run a file that still has one, so a half-annotated set can't quietly inflate the scores.
Each case carries a `_hint` (the section's opening text) to write the question from; the loader
ignores it. Keep these files under evals/private/ (git-ignored): they quote your documents.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .corpus import EVALS_DIR, load_doc


def draft(key: str, per_doc: int = 12) -> list[dict]:
    doc = load_doc(key)
    stem = Path(key).stem
    cases, seen = [], set()
    for c in doc.chunks:
        section = (c.section or "").strip()
        if not section or section in seen:
            continue
        seen.add(section)
        cases.append({"id": f"{stem}-{len(cases) + 1:02d}", "doc": key,
                      "question": f"TODO: a question a learner would ask about '{section}'",
                      "expect": "answer", "must_cite_pages": list(range(c.page_start, c.page_end + 1)),
                      "key_facts": ["TODO: a short phrase a correct answer must contain"],
                      "_hint": c.text[:240]})
        if len(cases) >= per_doc:
            break
    for i, q in enumerate(["What is the capital of France?", "Who won the most recent football World Cup?"], start=1):
        cases.append({"id": f"{stem}-nf{i}", "doc": key, "question": q, "expect": "not_found"})
    return cases


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    key = argv[0]
    if not (EVALS_DIR / key).exists():
        print(f"error: {EVALS_DIR / key} not found (paths are relative to evals/)", file=sys.stderr)
        return 2
    for case in draft(key):
        print(json.dumps(case, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
