"""Liveness and readiness endpoints."""
import dataclasses

from app import shared_state
from app.config import get_settings


def test_liveness(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_readiness_reports_database(client):
    r = client.get("/api/health/ready")
    assert r.status_code == 200 and r.json()["database"] == "ok" and "redis" not in r.json()


def test_readiness_is_503_when_redis_is_down(client, monkeypatch):
    shared_state.redis_client.cache_clear()
    s = dataclasses.replace(get_settings(), redis_url="redis://127.0.0.1:1/0")
    monkeypatch.setattr(shared_state, "get_settings", lambda: s)
    try:
        r = client.get("/api/health/ready")
        assert r.status_code == 503 and r.json()["redis"] == "unavailable" and r.json()["status"] == "degraded"
    finally:
        shared_state.redis_client.cache_clear()
