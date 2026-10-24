"""Knowledge-graph quality gates (P2).

    python -m evals.graph_eval [--provider mock|anthropic] [--gate]

* merge_precision / merge_recall: concept-merge rules on evals/gold/concept_merges.jsonl.
* mastery: knowledge tracing vs the old rules on simulated learners (evals.mastery_eval).
* concept_recall: share of gold concepts (evals/gold/graph.json) the extraction finds.
* grounding_rate: share of model-proposed concepts and edges whose quote checks out (kept / proposed).
* edge_precision / edge_recall: grounded prerequisite edges vs the gold edges (direction counts).

`--gate` fails on: merge_precision < 1.0, knowledge tracing worse than the rules, and (with the
real model only) edge_precision < EDGE_PRECISION_GATE. The mock's edges are synthetic
(consecutive concepts), so edge metrics are reported but not gated for it.
"""
from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

from app.ai.gateway import Request
from app.ai.prompts import CONCEPTS_SYSTEM, concepts_user
from app.core.concept_merge import rule_pairs, stem_key
from app.core.jsonutil import extract_json
from app.services.competency import rule_match
from app.services.concepts import pick_excerpts, validate_concepts, validate_prerequisites

from .corpus import EVALS_DIR, load_doc
from .mastery_eval import evaluate as mastery_evaluate
from .mastery_eval import simulate
from .run import make_gateway, make_provider

GOLD_GRAPH = EVALS_DIR / "gold" / "graph.json"
GOLD_MERGES = EVALS_DIR / "gold" / "concept_merges.jsonl"
EDGE_PRECISION_GATE = 0.8


def _same(a: str, b: str) -> bool:
    return stem_key(a) == stem_key(b) or rule_match(a, b)


def merge_metrics() -> dict:
    rows = [json.loads(line) for line in GOLD_MERGES.read_text().splitlines() if line.strip()]
    got = [(bool(rule_pairs([g["a"], g["b"]])), g["same"]) for g in rows]
    tp = sum(m and s for m, s in got)
    fp = sum(m and not s for m, s in got)
    fn = sum(s and not m for m, s in got)
    return {"merge_precision": tp / (tp + fp) if tp + fp else 1.0, "merge_recall": tp / (tp + fn) if tp + fn else 1.0}


def extraction_metrics(provider: str) -> dict:
    gold = json.loads(GOLD_GRAPH.read_text())
    gw = make_gateway(make_provider(provider))
    found_c = total_c = 0
    proposed = kept = 0
    tp_e = pred_e = gold_e = 0
    for key, g in gold.items():
        doc = load_doc(key)
        rows = [SimpleNamespace(id=c.id, ordinal=i, section=c.section, text=c.text, page_start=c.page_start,
                                page_end=c.page_end) for i, c in enumerate(doc.chunks)]
        sources = pick_excerpts(rows)
        out = gw.complete(Request(task="concept_extract", system=CONCEPTS_SYSTEM, user=concepts_user(sources),
                                  tier="fast", max_tokens=2000, context={"sources": sources}))
        data = extract_json(out.text)
        concepts = validate_concepts(data, sources)
        edges = validate_prerequisites(data, sources, concepts)
        proposed += len(data.get("concepts", [])) + len(data.get("prerequisites", []))
        kept += len(concepts) + len(edges)
        total_c += len(g["concepts"])
        found_c += sum(any(_same(gc, c.name) for c in concepts) for gc in g["concepts"])
        gold_pairs = [tuple(p) for p in g["prerequisites"]]
        gold_e += len(gold_pairs)
        pred_e += len(edges)
        tp_e += sum(any(_same(a, e.before) and _same(b, e.after) for a, b in gold_pairs) for e in edges)
        # recall counts gold edges found (each once)
    return {"concept_recall": found_c / total_c if total_c else 0.0,
            "grounding_rate": kept / proposed if proposed else 1.0,
            "edge_precision": tp_e / pred_e if pred_e else None,
            "edge_recall": tp_e / gold_e if gold_e else None,
            "edges_predicted": pred_e}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--provider", choices=("mock", "anthropic"), default="mock")
    p.add_argument("--gate", action="store_true")
    args = p.parse_args(argv)
    m = merge_metrics()
    mastery = mastery_evaluate(simulate(300, seed=7))
    x = extraction_metrics(args.provider)
    report = {**m, **x, "bkt_log_loss": mastery["bkt"]["log_loss"], "rules_log_loss": mastery["rules"]["log_loss"]}
    for k_, v in report.items():
        print(f"{k_:<18} {'n/a' if v is None else (f'{v:.3f}' if isinstance(v, float) else v)}")
    if not args.gate:
        return 0
    failures = []
    if m["merge_precision"] < 1.0:
        failures.append("merge_precision < 1.0 (a rule merged two different concepts)")
    if mastery["bkt"]["log_loss"] > mastery["rules"]["log_loss"]:
        failures.append("knowledge tracing predicts worse than the rules")
    if args.provider != "mock" and (x["edge_precision"] or 0) < EDGE_PRECISION_GATE:
        failures.append(f"edge_precision < {EDGE_PRECISION_GATE}")
    for f in failures:
        print("FAIL:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
