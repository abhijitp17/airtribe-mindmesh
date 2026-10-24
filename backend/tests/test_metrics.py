"""Service metrics: route templates (no ids), AI and job counters, a protected endpoint."""
import dataclasses
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{tmp}/t.db", "STORAGE_DIR": tmp, "AI_PROVIDER": "mock"})

from app import metrics  # noqa: E402
from app.config import get_settings  # noqa: E402


def _token(monkeypatch, token):
    s = dataclasses.replace(get_settings(), metrics_token=token)
    monkeypatch.setattr("app.main.get_settings", lambda: s)


def test_metrics_are_off_without_a_token_and_need_it_when_on(client, monkeypatch):
    _token(monkeypatch, None)
    assert client.get("/api/metrics").status_code == 404
    _token(monkeypatch, "s3cret")
    assert client.get("/api/metrics").status_code == 404
    assert client.get("/api/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 404
    assert client.get("/api/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_requests_are_labelled_by_route_template_never_by_id(client, sample_pdf, monkeypatch):
    _token(monkeypatch, "t")
    metrics.reset()
    r = client.post("/api/auth/signup", json={"email": "m@example.com", "password": "correct-horse-1"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    doc = client.post("/api/documents?rights_confirmed=true", headers=h,
                      files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()["id"]
    client.get(f"/api/documents/{doc}", headers=h)
    client.get("/api/does-not-exist")
    client.post("/api/tutor/ask", headers=h, json={"question": "What is Little's Law?", "document_ids": [doc]})
    text = client.get("/api/metrics", headers={"Authorization": "Bearer t"}).text
    assert 'route="/api/documents/{id}"' in text and doc not in text
    assert 'route="unmatched",status="404"' in text
    assert 'mindmesh_http_request_duration_seconds_bucket{route="/api/tutor/ask",le="+Inf"}' in text
    assert 'mindmesh_ai_calls_total{outcome="ok",task="tutor"}' in text
    assert "m@example.com" not in text


def test_render_format():
    metrics.reset()
    metrics.record_job("embed_document", "done")
    metrics.record_ai_call("tutor", 1.5, "ok")
    out = metrics.render()
    assert '# TYPE mindmesh_jobs_total counter\nmindmesh_jobs_total{kind="embed_document",outcome="done"} 1' in out
    assert 'mindmesh_ai_call_duration_seconds_bucket{task="tutor",le="2"} 1' in out
    assert 'mindmesh_ai_call_duration_seconds_bucket{task="tutor",le="1"} 0' in out
    assert 'mindmesh_ai_call_duration_seconds_count{task="tutor"} 1' in out
