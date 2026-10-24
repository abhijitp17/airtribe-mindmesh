"""Structured logs and error tracking (app/observability.py, access log in app/middleware.py)."""
import json
import logging
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_obs.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import observability  # noqa: E402
from app.main import app  # noqa: E402
from app.middleware import request_id_var  # noqa: E402
from app.observability import JsonFormatter, init_error_tracking, log_format, scrub_event  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_json_formatter_emits_one_object_with_extras_and_exception():
    token = request_id_var.set("rid-12345678")  # the record factory copies it onto every record
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.getLogger("mindmesh.t").makeRecord(
            "mindmesh.t", logging.ERROR, __file__, 1, "failed %s", ("x",), sys.exc_info(), extra={"status": 500},
        )
    finally:
        request_id_var.reset(token)
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "failed x" and out["level"] == "ERROR" and out["logger"] == "mindmesh.t"
    assert out["status"] == 500 and out["request_id"] == "rid-12345678"
    assert "ValueError: boom" in out["exc"] and out["ts"].endswith("+00:00")


def test_log_format_defaults(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    assert log_format("prod") == "json" and log_format("dev") == "text"
    monkeypatch.setenv("LOG_FORMAT", "json")
    assert log_format("dev") == "json"


def test_access_log_line_per_request_without_query_string(client, caplog):
    with caplog.at_level(logging.INFO, logger="mindmesh.access"):
        r = client.get("/api/documents?search=private+resume+text", headers={"X-Request-ID": "trace-abcdef12"})
    assert r.status_code == 401
    lines = [rec for rec in caplog.records if rec.name == "mindmesh.access"]
    assert len(lines) == 1
    rec = lines[0]
    assert rec.status == 401 and rec.method == "GET" and rec.path == "/api/documents"
    assert isinstance(rec.duration_ms, float) and rec.request_id == r.headers["x-request-id"] == "trace-abcdef12"
    assert "private" not in rec.getMessage() and "search" not in json.dumps(vars(rec), default=str)
    # uvicorn's own access log (full query string + client IP) is switched off.
    assert logging.getLogger("uvicorn.access").disabled


def test_scrub_event_drops_bodies_credentials_and_query():
    token = request_id_var.set("rid-12345678")
    try:
        event = scrub_event({"request": {
            "url": "https://api.example.com/api/tutor/ask?q=secret",
            "data": {"resume": "Priya Sharma ..."}, "cookies": {"s": "1"}, "query_string": "q=secret",
            "headers": {"Authorization": "Bearer abc", "User-Agent": "x"},
        }})
    finally:
        request_id_var.reset(token)
    req = event["request"]
    assert "data" not in req and "cookies" not in req and "query_string" not in req
    assert req["url"] == "https://api.example.com/api/tutor/ask"
    assert req["headers"] == {"User-Agent": "x"}
    assert event["tags"]["request_id"] == "rid-12345678"


def test_error_tracking_is_off_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_error_tracking("test") is False


def test_error_tracking_starts_with_privacy_options_and_scrubs_events(monkeypatch):
    import sentry_sdk

    sent: list[dict] = []
    real_init = sentry_sdk.init
    seen: dict = {}

    def init(**kwargs):
        seen.update(kwargs)
        # The real SDK must accept every option we pass; capture events instead of sending them.
        return real_init(**kwargs, transport=lambda envelope_or_event: sent.append(envelope_or_event))

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setattr(sentry_sdk, "init", init)
    try:
        assert init_error_tracking("test") is True
        assert seen["send_default_pii"] is False and seen["max_request_body_size"] == "never"
        assert seen["include_local_variables"] is False and seen["before_send"] is observability.scrub_event

        token = request_id_var.set("rid-87654321")
        try:
            sentry_sdk.capture_exception(RuntimeError("ingestion crashed"))
        finally:
            request_id_var.reset(token)
        sentry_sdk.flush()
    finally:
        real_init(dsn=None)  # switch the SDK off for the rest of the run
    events = [e for e in sent if isinstance(e, dict)] or [
        item.payload.json for env in sent for item in getattr(env, "items", []) if item.type == "event"]
    assert events and events[0]["tags"]["request_id"] == "rid-87654321"
