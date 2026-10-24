"""Eval CLI: run the gold set through the real tutor and quiz pipeline.

    python -m evals.run [--provider mock|anthropic] [--k 6] [--out report.json]
                        [--baseline evals/baseline.json] [--tolerance 0.02]
                        [--fail-under-citation 0.95] [--docs docs/finance.txt ...]

Exit codes: 0 ok, 1 regression or threshold failure, 2 usage/config error.
Run from ``backend/`` so ``app`` and ``evals`` are importable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from app.ai.gateway import PROMPT_VERSION, Completion, Gateway, Provider, Request
from app.core.assessment import InvalidQuestion, validate_question
from app.core.jsonutil import JSONExtractionError, extract_json
from app.services.learning import ChunkData, ask_tutor, generate_quiz, retrieve

from .corpus import EVALS_DIR, IngestedDoc, load_doc
from .dataset import GoldCase, QuizConfig, QuizSpec, load_gold, load_quiz_config
from .metrics import METRIC_NAMES, CaseOutcome, Delta, QuizOutcome, build_report, compare, regressions

DEFAULT_GOLD = EVALS_DIR / "gold" / "qa.jsonl"
DEFAULT_QUIZ = EVALS_DIR / "gold" / "quiz.json"
DEFAULT_TOLERANCE = 0.02
QUIZ_TASK = "quiz_generate"


@dataclass
class RecordingProvider:
    """Wraps a provider and keeps the last quiz completion plus its request.

    ``generate_quiz`` only returns questions that survived validation; the
    eval also needs the raw model output to measure question validity.
    """

    inner: Provider
    name: str = "recording"
    last_quiz: tuple[Request, str] | None = field(default=None, init=False)

    def complete(self, req: Request, model: str) -> Completion:
        out = self.inner.complete(req, model)
        if req.task.removesuffix("_repair") == QUIZ_TASK:
            self.last_quiz = (req, out.text)
        return out


def make_provider(name: str) -> Provider:
    if name == "mock":
        from app.ai.mock import MockProvider

        return MockProvider()
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("error: --provider anthropic needs ANTHROPIC_API_KEY")
    from app.ai.gateway import AnthropicProvider

    return AnthropicProvider(key)


def make_gateway(provider: Provider, main: str | None = None, fast: str | None = None) -> Gateway:
    main = main or os.getenv("ANTHROPIC_MODEL_MAIN", "claude-sonnet-4-5")
    fast = fast or os.getenv("ANTHROPIC_MODEL_FAST", "claude-haiku-4-5")
    return Gateway(provider, main, fast, max_retries=1)


def spans(items: Sequence[object]) -> tuple[tuple[int, int], ...]:
    return tuple((int(getattr(i, "page_start")), int(getattr(i, "page_end"))) for i in items)


class DenseIndex:
    """Embeds each eval document's chunks once with a dense provider (core.dense); scores queries."""

    def __init__(self, provider):
        self.provider = provider
        self._vecs: dict[tuple[str, ...], object] = {}

    def scores(self, chunks: Sequence[ChunkData], query: str) -> dict[str, float]:
        from app.core.dense import DenseScorer

        key = tuple(c.id for c in chunks)
        if key not in self._vecs:
            self._vecs[key] = self.provider.embed([f"{c.section}\n{c.text}".strip() for c in chunks], "document")
        return DenseScorer(list(key), self._vecs[key], self.provider.embed([query], "query")[0]).scores()


def run_case(gw: Gateway, case: GoldCase, chunks: Sequence[ChunkData], k: int, dense: DenseIndex | None = None) -> CaseOutcome:
    scores = dense.scores(chunks, case.question) if dense else None
    result = ask_tutor(gw, chunks, case.question, level=case.level, dense=scores)
    return CaseOutcome(
        id=case.id,
        doc=case.doc,
        expect=case.expect,
        status=result.status,
        answer=result.answer,
        must_cite_pages=case.must_cite_pages,
        key_facts=case.key_facts,
        citation_spans=tuple((c["page_start"], c["page_end"]) for c in result.citations),
        retrieved_spans=spans(retrieve(chunks, case.question, k=k, dense=scores)),
        must_not_contain=case.must_not_contain,
    )


def count_valid(text: str, req: Request) -> tuple[int, int]:
    """(raw, valid) question counts in a quiz completion, validated like production."""
    try:
        data = extract_json(text)
    except JSONExtractionError:
        return 0, 0
    items = data.get("questions", []) if isinstance(data, dict) else []
    labels = {s.label for s in req.context.get("sources", [])}
    valid = 0
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            validate_question(raw, labels)
            valid += 1
        except InvalidQuestion:
            pass
    return len(items), valid


def run_quiz(gw: Gateway, rec: RecordingProvider, spec: QuizSpec, chunks: Sequence[ChunkData], cfg: QuizConfig) -> QuizOutcome:
    rec.last_quiz = None
    kept = generate_quiz(gw, chunks, count=cfg.count, difficulty=cfg.difficulty, focus=spec.focus)
    raw, valid = count_valid(rec.last_quiz[1], rec.last_quiz[0]) if rec.last_quiz else (0, 0)
    return QuizOutcome(spec.doc, spec.focus, cfg.count, raw, valid, len(kept), tuple(q.spec.type for q in kept))


def run_eval(
    provider: Provider,
    cases: Sequence[GoldCase],
    quiz_cfg: QuizConfig,
    k: int,
    meta: dict,
    models: tuple[str, str] | None = None,
    dense_provider=None,
) -> dict:
    """Ingest every referenced doc once, run QA and quiz evals, return the report.
    `models` = (main, fast) overrides ANTHROPIC_MODEL_MAIN / _FAST (used by evals.compare_models)."""
    rec = RecordingProvider(provider)
    gw = make_gateway(rec, *(models or (None, None)))
    keys = sorted({c.doc for c in cases} | {q.doc for q in quiz_cfg.runs})
    docs: dict[str, IngestedDoc] = {key: load_doc(key) for key in keys}
    dense = DenseIndex(dense_provider) if dense_provider is not None else None
    outcomes = [run_case(gw, c, docs[c.doc].chunks, k, dense) for c in cases]
    quizzes = [run_quiz(gw, rec, q, docs[q.doc].chunks, quiz_cfg) for q in quiz_cfg.runs]
    meta = {**meta, "docs": {key: {"pages": d.page_count, "chunks": len(d.chunks)} for key, d in docs.items()}}
    return build_report(outcomes, quizzes, meta)


def _fmt(v: float | None) -> str:
    return "  n/a" if v is None else f"{v:5.3f}"


def _fmt_change(d: Delta, tolerance: float) -> str:
    if d.change is None:
        return "REGRESSED (now n/a)" if d.regressed(tolerance) else ""
    flag = "  REGRESSED" if d.regressed(tolerance) else ""
    return f"{d.change:+.3f}{flag}"


def format_table(report: dict, deltas: Sequence[Delta] | None = None, tolerance: float = DEFAULT_TOLERANCE) -> str:
    """Human-readable summary: overall metrics, per-doc columns, optional deltas."""
    docs = list(report["by_doc"])
    header = f"{'metric':<26}{'overall':>9}" + "".join(f"{Path(d).stem[:12]:>14}" for d in docs)
    if deltas is not None:
        header += f"{'baseline':>10}  delta"
    by_metric = {d.metric: d for d in deltas or []}
    lines = [header, "-" * len(header)]
    for m in METRIC_NAMES:
        row = f"{m:<26}{_fmt(report['metrics'][m]):>9}" + "".join(f"{_fmt(report['by_doc'][d][m]):>14}" for d in docs)
        if deltas is not None:
            d = by_metric[m]
            row += f"{_fmt(d.baseline):>10}  {_fmt_change(d, tolerance)}"
        lines.append(row)
    c = report["counts"]
    lines.append(
        f"\n{c['cases']} QA cases ({c['answerable']} answerable, {c['not_found']} not_found); "
        f"{c['quizzes']} quizzes, {c['generated_questions']} generated questions."
    )
    for label, key in (("Retrieval misses@k", "retrieval_hit"), ("Top-1 misses", "top1_hit")):
        misses = [r["id"] for r in report["cases"] if r[key] is False]
        if misses:
            lines.append(f"{label}: {', '.join(misses)}")
    false_answers = [r["id"] for r in report["cases"] if r["expect"] == "not_found" and r["status"] != "not_found"]
    if false_answers:
        lines.append(f"Answered but should be not_found: {', '.join(false_answers)}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__.split("\n")[0])
    p.add_argument("--provider", choices=("mock", "anthropic"), default="mock")
    p.add_argument("--k", type=int, default=6, help="retrieval depth for recall@k (default 6)")
    p.add_argument("--dense", choices=("off", "fake", "voyage"), default="off",
                   help="add learned-embedding retrieval (voyage needs VOYAGE_API_KEY; set DENSE_FOUND_THRESHOLD "
                        "from evals.calibrate_dense to let it take part in the coverage gate)")
    p.add_argument("--gold", type=Path, default=DEFAULT_GOLD, help="QA gold set (JSONL)")
    p.add_argument("--quiz", type=Path, default=DEFAULT_QUIZ, help="quiz eval config (JSON)")
    p.add_argument("--docs", nargs="*", help="only run cases for these doc keys, e.g. docs/finance.txt")
    p.add_argument("--out", type=Path, help="write the JSON report here")
    p.add_argument("--baseline", type=Path, help="compare against a saved report and fail on regressions")
    p.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="allowed drop per metric (default 0.02)")
    p.add_argument("--fail-under-citation", type=float, metavar="RATE",
                   help="fail if citation_validity_rate is below RATE")
    p.add_argument("--fail-under-injection", type=float, metavar="RATE",
                   help="fail if injection_resistance is below RATE (adversarial gold set)")
    args = p.parse_args(argv)
    if args.k < 1:
        p.error("--k must be >= 1")
    return args


def filter_docs(cases: list[GoldCase], cfg: QuizConfig, docs: Sequence[str] | None) -> tuple[list[GoldCase], QuizConfig]:
    if not docs:
        return cases, cfg
    keep = set(docs)
    runs = tuple(r for r in cfg.runs if r.doc in keep)
    return [c for c in cases if c.doc in keep], QuizConfig(cfg.count, cfg.difficulty, runs)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    cases, quiz_cfg = filter_docs(load_gold(args.gold), load_quiz_config(args.quiz), args.docs)
    if not cases:
        print("error: no gold cases selected", file=sys.stderr)
        return 2
    meta = {"provider": args.provider, "k": args.k, "prompt_version": PROMPT_VERSION,
            "gold": args.gold.name, "quiz_config": args.quiz.name}
    dense_provider = None
    if args.dense != "off":
        from app.core.dense import get_dense_provider

        dense_provider = get_dense_provider(args.dense)
        if dense_provider is None:
            print("error: dense provider unavailable (VOYAGE_API_KEY?)", file=sys.stderr)
            return 2
        meta["dense"] = dense_provider.name
    report = run_eval(make_provider(args.provider), cases, quiz_cfg, args.k, meta, dense_provider=dense_provider)

    deltas = None
    if args.baseline:
        deltas = compare(report, json.loads(args.baseline.read_text(encoding="utf-8")))
    print(format_table(report, deltas, args.tolerance))

    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nReport written to {args.out}")

    failed = False
    if deltas is not None and (bad := regressions(deltas, args.tolerance)):
        print(f"\nFAIL: {len(bad)} metric(s) regressed beyond tolerance {args.tolerance}: "
              + ", ".join(d.metric for d in bad), file=sys.stderr)
        failed = True
    rate = report["metrics"]["citation_validity_rate"]
    if args.fail_under_citation is not None and (rate is None or rate < args.fail_under_citation):
        print(f"\nFAIL: citation_validity_rate {_fmt(rate).strip()} < {args.fail_under_citation}", file=sys.stderr)
        failed = True
    inj = report["metrics"].get("injection_resistance")
    if args.fail_under_injection is not None and (inj is None or inj < args.fail_under_injection):
        print(f"\nFAIL: injection_resistance {_fmt(inj).strip()} < {args.fail_under_injection}", file=sys.stderr)
        for row in report.get("cases", []):
            if row.get("injection_resisted") is False:
                print(f"  leaked canary: {row['id']}", file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
