"""Reporting bad questions: reasons, the user's own triage list, undo, and the content-free ops report."""
import json
import time

from app.tools.flag_report import build_report


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _quiz(client, h, sample_pdf):
    doc = client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()
    for _ in range(50):
        if client.get(f"/api/documents/{doc['id']}", headers=h).json()["status"] == "ready":
            break
        time.sleep(0.05)
    quiz = client.post("/api/quizzes", headers=h, json={"document_ids": [doc["id"]], "count": 3}).json()
    for q in quiz["questions"]:
        body = {"selected_index": 0} if q["qtype"] == "mcq" else {"answer_text": "work in process equals throughput times cycle time"}
        assert client.post(f"/api/questions/{q['id']}/attempts", headers=h, json=body).status_code == 201
    return quiz


def _attempts(client, h):
    return client.get("/api/progress", headers=h).json()["totals"]["attempts"]


def test_report_with_reason_then_undo(client, sample_pdf):
    h = _signup(client, "reporter@example.com")
    quiz = _quiz(client, h, sample_pdf)
    q = quiz["questions"][0]
    before = _attempts(client, h)

    r = client.post(f"/api/questions/{q['id']}/flag", headers=h, json={"reason": "wrong_answer", "note": "Option B is also right"})
    assert r.status_code == 204
    listed = client.get("/api/questions/flagged", headers=h).json()
    assert [(x["id"], x["reason"], x["note"]) for x in listed] == [(q["id"], "wrong_answer", "Option B is also right")]
    assert listed[0]["quiz_title"] and listed[0]["flagged_at"]
    assert _attempts(client, h) == before - 1, "reported questions don't count towards mastery"
    assert client.get(f"/api/quizzes/{quiz['id']}", headers=h).json()["questions"][0]["flagged"] is True

    assert client.delete(f"/api/questions/{q['id']}/flag", headers=h).status_code == 204
    assert client.get("/api/questions/flagged", headers=h).json() == []
    assert _attempts(client, h) == before, "undo makes it count again"


def test_reason_without_note_and_legacy_free_text(client, sample_pdf):
    h = _signup(client, "legacy@example.com")
    qs = _quiz(client, h, sample_pdf)["questions"]
    client.post(f"/api/questions/{qs[0]['id']}/flag", headers=h, json={"reason": "unclear"})
    client.post(f"/api/questions/{qs[1]['id']}/flag", headers=h, json={"reason": "the wording is confusing"})
    by_id = {x["id"]: x for x in client.get("/api/questions/flagged", headers=h).json()}
    assert (by_id[qs[0]["id"]]["reason"], by_id[qs[0]["id"]]["note"]) == ("unclear", "")
    assert (by_id[qs[1]["id"]]["reason"], by_id[qs[1]["id"]]["note"]) == ("other", "the wording is confusing")


def test_reports_are_private(client, sample_pdf):
    owner = _signup(client, "owner-flag@example.com")
    other = _signup(client, "other-flag@example.com")
    q = _quiz(client, owner, sample_pdf)["questions"][0]
    assert client.post(f"/api/questions/{q['id']}/flag", headers=other, json={"reason": "unclear"}).status_code == 404
    client.post(f"/api/questions/{q['id']}/flag", headers=owner, json={"reason": "unclear"})
    assert client.delete(f"/api/questions/{q['id']}/flag", headers=other).status_code == 404
    assert client.get("/api/questions/flagged", headers=other).json() == []


def test_ops_report_counts_without_content(client, sample_pdf):
    h = _signup(client, "ops@example.com")
    qs = _quiz(client, h, sample_pdf)["questions"]
    client.post(f"/api/questions/{qs[0]['id']}/flag", headers=h, json={"reason": "not_in_document", "note": "SECRET-NOTE-123"})
    report = build_report(days=1)
    assert report and all(set(r) >= {"generator", "questions", "reported", "report_rate", "by_reason"} for r in report)
    assert sum(r["reported"] for r in report) >= 1
    assert any(r["by_reason"].get("not_in_document") for r in report)
    dumped = json.dumps(report)
    assert "SECRET-NOTE-123" not in dumped
    assert all(q["prompt"] not in dumped for q in qs), "no question text in the operator report"
