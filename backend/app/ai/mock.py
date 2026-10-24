"""Deterministic offline provider.

Lets the whole app run, demo and be tested without an API key. Outputs follow
the same JSON contracts as the real prompts and are built from the actual
retrieved sources, so citation verification and question validation are
exercised for real.
"""
from __future__ import annotations

import json
import os
import re
import time

from ..core.text import tokenize
from .gateway import Completion, Request

_LATENCY_S = float(os.getenv("MOCK_LATENCY_MS", "0")) / 1000


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if len(s.split()) >= 6]


# Feature modules register offline handlers here instead of editing this file:
#
#     # app/ai/mock_interview.py
#     from .mock import register_mock
#     @register_mock("jd_parse")
#     def _jd_parse(ctx: dict) -> dict: ...
#
# Every module named app/ai/mock_*.py is imported automatically on first use.
_REGISTRY: dict[str, "callable"] = {}
_loaded = False


def register_mock(task: str):
    def deco(fn):
        _REGISTRY[task] = fn
        return fn
    return deco


def _load_feature_mocks() -> None:
    global _loaded
    if _loaded:
        return
    import importlib
    import pkgutil
    from pathlib import Path

    for m in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if m.name.startswith("mock_"):
            importlib.import_module(f"{__package__}.{m.name}")
    _loaded = True


class MockProvider:
    name = "mock"

    def complete(self, req: Request, model: str) -> Completion:
        if _LATENCY_S:  # load tests: simulate a real model's latency
            time.sleep(_LATENCY_S)
        _load_feature_mocks()
        task = req.task.removesuffix("_repair")
        handler = _REGISTRY.get(task) or getattr(self, f"_{task}", None)
        payload = handler(req.context) if handler else {"answer": "Mock response."}
        text = json.dumps(payload)
        return Completion(text, f"mock-{model}", len(req.user) // 4, len(text) // 4)

    # ---- tasks ----
    def _tutor(self, ctx: dict) -> dict:
        sources = ctx.get("sources", [])
        q_terms = set(tokenize(ctx.get("question", "")))
        scored = []
        for s in sources:
            for sent in _sentences(s.text):
                overlap = len(q_terms & set(tokenize(sent)))
                if overlap:
                    scored.append((overlap, s.label, sent))
        if not scored:
            return {"found": False, "answer": "Your documents don't appear to cover this question.", "citations": []}
        scored.sort(key=lambda x: -x[0])
        picked, seen = [], set()
        for _, label, sent in scored:
            if label not in seen:
                picked.append((label, sent))
                seen.add(label)
            if len(picked) == 2:
                break
        answer = " ".join(f"{sent} [{label}]" for label, sent in picked)
        prefix = "In simple terms: " if ctx.get("level") == "beginner" else ""
        return {
            "found": True,
            "answer": f"{prefix}{answer}\n\n_(Offline mock tutor: set ANTHROPIC_API_KEY for real explanations.)_",
            "citations": [{"source": label, "quote": " ".join(sent.split()[:20])} for label, sent in picked],
        }

    def _general(self, ctx: dict) -> dict:
        return {"answer": "General-knowledge mode is unavailable in offline mock mode."}

    def _quiz_generate(self, ctx: dict) -> dict:
        sources = ctx.get("sources", [])
        mix: dict[str, int] = ctx.get("mix", {"mcq": 3})
        sents = [(s.label, s.section, sent) for s in sources for sent in _sentences(s.text)]
        if not sents:
            return {"questions": []}
        wanted = [t for t, n in mix.items() for _ in range(n)]
        questions = []
        for i, qtype in enumerate(wanted):
            label, section, sent = sents[i % len(sents)]
            concept = re.sub(r"^[\d.\s]+", "", section.split(" > ")[-1]).strip() or "Key idea"
            words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{4,}", sent)]
            target = max(words, key=len) if words else "concept"
            if qtype == "mcq":
                distract = sorted({w for _, _, s in sents for w in re.findall(r"[A-Za-z][A-Za-z'-]{4,}", s)} - {target})
                opts = [target] + (distract[i % max(1, len(distract)) :] + distract)[:3]
                while len(opts) < 4:
                    opts.append(f"None of the listed ({len(opts)})")
                rot = i % 4
                opts = opts[rot:] + opts[:rot]
                questions.append({
                    "type": "mcq", "concept": concept, "difficulty": "easy",
                    "prompt": f"Fill in the blank: \"{sent.replace(target, '_____', 1)}\"",
                    "options": opts, "correct_index": opts.index(target),
                    "explanation": f"The source says: \"{sent}\"", "sources": [label],
                })
            else:
                verb = "Explain in your own words" if qtype == "short" else "Give a realistic workplace example that applies"
                key_terms = sorted(set(words), key=len, reverse=True)[:2] or ["the idea"]
                questions.append({
                    "type": qtype, "concept": concept, "difficulty": "medium",
                    "prompt": f"{verb}: {sent}",
                    "answer_key": sent,
                    "rubric": [{"criterion": f"Mentions {t}", "points": 1} for t in key_terms]
                    + [{"criterion": "Reasoning is accurate and complete", "points": 2}],
                    "explanation": f"See source: \"{sent}\"", "sources": [label],
                })
        return {"questions": questions}

    def _grade(self, ctx: dict) -> dict:
        answer = ctx.get("answer", "")
        key = ctx.get("answer_key", "")
        a_terms = set(tokenize(answer))
        overlap = len(a_terms & set(tokenize(key))) / max(1, len(set(tokenize(key))))
        out = []
        for r in ctx.get("rubric", []):
            crit = r["criterion"]
            if crit.startswith("Mentions "):
                term = set(tokenize(crit[len("Mentions "):]))
                status = "met" if term and term <= a_terms else "missing"
            else:
                status = "met" if overlap >= 0.6 else "partial" if overlap >= 0.25 else "missing"
            out.append({"criterion": crit, "status": status, "evidence": answer[:120] if status != "missing" else ""})
        return {"criteria": out, "feedback": f"Offline mock grading based on overlap with the model answer ({overlap:.0%}). Model answer: {key}"}
