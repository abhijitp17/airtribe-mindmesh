"""Provider-agnostic model gateway (PRD 11.2 "AI gateway").

All model calls go through `Gateway`, which gives us one place for model
routing (main vs fast tier), retries, structured-output parsing with a repair
attempt, per-user token budgets, and usage accounting. Providers only have to
implement `complete()`.

Prompts and document text are never logged here; only metadata.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..core.jsonutil import JSONExtractionError, extract_json
from ..metrics import record_ai_call

log = logging.getLogger("mindmesh.ai")

PROMPT_VERSION = "2026-10-09.1"


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Request:
    task: str  # e.g. "tutor", "quiz_generate", "grade"
    system: str
    user: str
    tier: str = "main"  # "main" | "fast"
    max_tokens: int = 2000
    temperature: float = 0.2  # mock provider only: current Anthropic models reject sampling parameters
    # Structured context for the mock provider; real providers ignore it.
    context: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str

    def complete(self, req: Request, model: str) -> Completion: ...


class BudgetExceeded(Exception):
    pass


class ModelError(Exception):
    pass


class ModelRefused(ModelError):
    """The model (and any server-side fallback) declined the request. Not retried: it would decline again."""


@dataclass
class Usage:
    task: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    prompt_version: str = PROMPT_VERSION


class Gateway:
    def __init__(
        self,
        provider: Provider,
        model_main: str,
        model_fast: str,
        budget_check: Callable[[int], None] | None = None,
        on_usage: Callable[[Usage], None] | None = None,
        before_call: Callable[[], None] | None = None,
        max_retries: int = 2,
    ):
        self.provider = provider
        self.models = {"main": model_main, "fast": model_fast}
        self.budget_check = budget_check
        self.on_usage = on_usage
        self.before_call = before_call  # e.g. release the request's DB connection during the model call
        self.max_retries = max_retries

    def complete(self, req: Request) -> Completion:
        if self.budget_check:
            self.budget_check(req.max_tokens)
        if self.before_call:
            self.before_call()
        model = self.models.get(req.tier, self.models["main"])
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            start = time.monotonic()
            try:
                out = self.provider.complete(req, model)
            except ModelRefused:
                record_ai_call(req.task, time.monotonic() - start, "refused")
                raise
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - provider errors are retried
                last_exc = exc
                log.warning("model call failed task=%s attempt=%d err=%s", req.task, attempt, type(exc).__name__)
                time.sleep(min(4.0, 0.5 * 2**attempt))
                continue
            record_ai_call(req.task, time.monotonic() - start, "ok")
            usage = Usage(req.task, out.model, out.input_tokens, out.output_tokens, int((time.monotonic() - start) * 1000))
            log.info("model call task=%s model=%s in=%d out=%d ms=%d", usage.task, usage.model, usage.input_tokens, usage.output_tokens, usage.latency_ms)
            if self.on_usage:
                self.on_usage(usage)
            return out
        record_ai_call(req.task, 0.0, "error")
        raise ModelError(f"Model call failed after retries: {last_exc}") from last_exc

    def complete_json(self, req: Request, validate: Callable[[Any], Any] | None = None) -> Any:
        """Call the model and parse JSON; on failure, ask once for a repair."""
        out = self.complete(req)
        try:
            data = extract_json(out.text)
            return validate(data) if validate else data
        except (JSONExtractionError, ValueError, KeyError, TypeError) as exc:
            repair = Request(
                task=f"{req.task}_repair",
                system=req.system,
                user=(
                    f"{req.user}\n\nYour previous reply could not be used ({type(exc).__name__}: {exc}). "
                    "Reply again with ONLY a single valid JSON object that follows the schema exactly."
                ),
                tier=req.tier,
                max_tokens=req.max_tokens,
                temperature=0.0,
                context=req.context,
            )
            data = extract_json(self.complete(repair).text)
            return validate(data) if validate else data


# Models with server-side refusal fallbacks ("default" routes by refusal category). Claude Haiku 5.5 has none.
SERVER_FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1")
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
MIN_MAX_TOKENS = 16_000  # thinking counts against max_tokens; a low cap truncated JSON answers


def _is_v5(model: str) -> bool:
    """Claude 5-generation models: adaptive thinking on by default and `output_config.effort` accepted."""
    return bool(re.match(r"claude-[a-z]+-5(-|$)", model))


class AnthropicProvider:
    """Claude via the official SDK (anthropic>=1).

    * No sampling parameters: the 1.x SDK has no `temperature`, and Claude 5-generation models
      reject non-default sampling. (Passing temperature made every real call fail with a TypeError.)
    * Effort per tier for 5-generation models (ANTHROPIC_EFFORT_MAIN / _FAST); 4.x models reject it.
    * Sonnet/Opus/Fable 5.x requests carry server-side refusal fallbacks.
    * A refusal raises ModelRefused (not retried); a max_tokens stop raises ModelError, never half a JSON.
    """

    name = "anthropic"

    def __init__(self, api_key: str, timeout: float = 90.0, client: Any | None = None,
                 effort: dict[str, str | None] | None = None):
        if client is None:
            import anthropic  # imported lazily so tests and mock mode don't need it

            client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)
        self.client = client
        self.effort = effort if effort is not None else {
            "main": os.getenv("ANTHROPIC_EFFORT_MAIN") or None, "fast": os.getenv("ANTHROPIC_EFFORT_FAST") or None,
        }

    def request_kwargs(self, req: Request, model: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max(req.max_tokens, MIN_MAX_TOKENS),
            "system": req.system,
            "messages": [{"role": "user", "content": req.user}],
        }
        effort = self.effort.get(req.tier)
        if effort and _is_v5(model):
            kwargs["output_config"] = {"effort": effort}
        if model in SERVER_FALLBACK_MODELS:
            kwargs["betas"] = [SERVER_FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    def complete(self, req: Request, model: str) -> Completion:
        kwargs = self.request_kwargs(req, model)
        create = self.client.beta.messages.create if "betas" in kwargs else self.client.messages.create
        resp = create(**kwargs)
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            raise ModelRefused(f"declined ({getattr(details, 'category', None) or 'unspecified'})")
        if resp.stop_reason == "max_tokens":
            raise ModelError(f"response hit max_tokens ({kwargs['max_tokens']}) for task {req.task}")
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return Completion(text, resp.model, resp.usage.input_tokens, resp.usage.output_tokens)
