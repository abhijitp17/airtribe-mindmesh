"""Structured logs and optional error tracking.

Logs
  LOG_FORMAT=json|text (default: json when APP_ENV=prod, text otherwise), LOG_LEVEL (default INFO).
  Every line carries the request id (app.middleware). JSON lines also carry any `extra=`
  fields, e.g. the per-request access line: method, path, status, duration_ms.

Error tracking (off unless SENTRY_DSN is set; any Sentry-compatible endpoint works)
  Mindmesh handles resumes and private documents, so events never include request
  bodies, local variables, cookies, auth headers or query strings. Each event is tagged
  with the request id so it can be matched to the logs.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Standard record attributes, plus uvicorn's ANSI-coloured duplicate of the message.
_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message", "asctime", "request_id", "color_message"}
_configured = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        out.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def log_format(env: str | None = None) -> str:
    fmt = os.getenv("LOG_FORMAT", "").strip().lower()
    if fmt in ("json", "text"):
        return fmt
    return "json" if (env or os.getenv("APP_ENV", "dev")) == "prod" else "text"


def setup_logging(env: str | None = None) -> None:
    """Idempotent. Gives app loggers a stdout handler and, in JSON mode, puts uvicorn's logs in JSON too."""
    global _configured
    if _configured:
        return
    _configured = True
    fmt = log_format(env)
    formatter: logging.Formatter = (
        JsonFormatter() if fmt == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    elif fmt == "json":
        for h in root.handlers:
            h.setFormatter(formatter)
    logging.getLogger("mindmesh").setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    # mindmesh.access replaces uvicorn's access log, which records full query strings and client IPs.
    logging.getLogger("uvicorn.access").disabled = True
    if fmt == "json":
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            for h in logging.getLogger(name).handlers:
                h.setFormatter(formatter)


# ---------------------------------------------------------------- error tracking

_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key"}


def scrub_event(event: dict[str, Any], _hint: Any = None) -> dict[str, Any]:
    """Sentry before_send: drop anything that could carry resume/document text or credentials."""
    from .middleware import request_id_var

    req = event.get("request")
    if isinstance(req, dict):
        for key in ("data", "cookies", "query_string", "env"):
            req.pop(key, None)
        headers = req.get("headers")
        if isinstance(headers, dict):
            req["headers"] = {k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_HEADERS}
        if isinstance(req.get("url"), str):
            req["url"] = req["url"].split("?", 1)[0]
    rid = request_id_var.get()
    if rid and rid != "-":
        event.setdefault("tags", {})["request_id"] = rid
    return event


def init_error_tracking(env: str | None = None) -> bool:
    """Start Sentry if SENTRY_DSN is set. Returns whether it was started."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=env or os.getenv("APP_ENV", "dev"),
        release=os.getenv("RELEASE") or None,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0") or 0),
        before_send=scrub_event,
    )
    return True
