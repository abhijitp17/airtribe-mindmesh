"""Notes-first answers: how often the knowledge base answers without the AI, and that it's never wrong.

    python -m evals.notes_eval [--gate]

Runs the no-model path (retrieval, coverage check, router, extractive answer) over the gold QA set
and the adversarial set:
  local_rate       answerable questions answered from notes (higher saves more tokens)
  local_precision  local answers citing at least one expected page
  not_found_leaks  off-topic questions answered from notes (must be 0)
  injection_leaks  local answers containing planted text the gold set forbids (must be 0)
--gate fails on any leak or local_precision < PRECISION_GATE.
"""
from __future__ import annotations

import argparse

from app.core.notes_first import classify, extract
from app.services.learning import lexical_coverage, retrieve

from .corpus import EVALS_DIR, load_doc
from .dataset import load_gold

PRECISION_GATE = 0.9


def local_answer(chunks, question):
    if classify(question).kind == "synthesis":
        return None
    sources = retrieve(chunks, question)
    if lexical_coverage(chunks, question, sources) != "confident":
        return None
    return extract(question, sources)


def run() -> dict:
    cases = load_gold(EVALS_DIR / "gold" / "qa.jsonl") + load_gold(EVALS_DIR / "gold" / "adversarial.jsonl")
    docs = {c.doc: load_doc(c.doc) for c in cases}
    answerable = local = correct = nf_leaks = inj_leaks = 0
    for c in cases:
        ex = local_answer(docs[c.doc].chunks, c.question)
        if c.expect == "not_found":
            nf_leaks += ex is not None
            continue
        answerable += 1
        if ex is None:
            continue
        local += 1
        pages = {p for cite in ex.citations for p in range(cite["page_start"], cite["page_end"] + 1)}
        correct += (not c.must_cite_pages) or bool(pages & set(c.must_cite_pages))
        inj_leaks += any(bad.lower() in ex.answer.lower() for bad in (c.must_not_contain or []))
    return {"cases": len(cases), "local_rate": local / answerable if answerable else 0.0,
            "local_precision": correct / local if local else 1.0, "not_found_leaks": nf_leaks,
            "injection_leaks": inj_leaks}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--gate", action="store_true")
    args = p.parse_args(argv)
    r = run()
    for k, v in r.items():
        print(f"{k:<16} {v:.3f}" if isinstance(v, float) else f"{k:<16} {v}")
    fails = [m for m, bad in (("not_found_leaks", r["not_found_leaks"] > 0), ("injection_leaks", r["injection_leaks"] > 0),
                              ("local_precision", r["local_precision"] < PRECISION_GATE)) if bad]
    for f in fails:
        print("FAIL:", f)
    return 1 if args.gate and fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
