"""API tests for goals & plans (CONTRACTS §4). Needs backend deps; runs in CI."""
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_goals.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


def _today():
    # Requests here send no X-Timezone, so the API's "today" is the UTC date (app/clock.py).
    return datetime.now(timezone.utc).date()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _upload(client, headers, pdf):
    r = client.post("/api/documents?rights_confirmed=true", headers=headers, files={"file": ("fp.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    for _ in range(50):
        d = client.get(f"/api/documents/{doc_id}", headers=headers).json()
        if d["status"] not in ("uploaded", "processing"):
            return d
        time.sleep(0.05)
    raise AssertionError("processing did not finish")


def _goal(client, h, doc_id, **kw):
    body = {
        "goal_type": "learn", "title": "Learn factory physics", "deadline": (_today() + timedelta(days=21)).isoformat(),
        "minutes_per_day": 45, "study_days": ALL_DAYS, "document_ids": [doc_id], **kw,
    }
    r = client.post("/api/goals", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _daily(items):
    load = {}
    for i in items:
        if i["status"] != "skipped":
            load[i["scheduled_date"]] = load.get(i["scheduled_date"], 0) + i["estimated_minutes"]
    return load


def test_create_goal_builds_feasible_plan(client, sample_pdf):
    h = _signup(client, "goal-a@example.com")
    doc = _upload(client, h, sample_pdf)
    g = _goal(client, h, doc["id"])
    assert g["goal_type"] == "learn" and g["status"] == "active" and g["pending_proposal"] is None
    assert g["items"], "plan should be generated"
    assert all(v <= 45 for v in _daily(g["items"]).values())
    assert all(i["scheduled_date"] <= g["deadline"] for i in g["items"])
    assert {i["activity_type"] for i in g["items"]} >= {"learn", "practice"}
    first = g["items"][0]
    assert first["sources"] and first["sources"][0]["document_id"] == doc["id"]
    assert set(first) == {"id", "position", "scheduled_date", "topic", "concept", "activity_type", "estimated_minutes",
                          "objective", "sources", "status", "user_edited", "reason"}
    assert set(g["stats"]) == {"total_minutes", "done_minutes", "items_done", "items_total", "on_track", "days_left", "capacity_minutes"}
    assert g["stats"]["on_track"] is True and g["stats"]["days_left"] == 21

    summary = client.get("/api/goals", headers=h).json()
    assert summary[0]["id"] == g["id"] and summary[0]["items_total"] == g["stats"]["items_total"]
    assert client.get(f"/api/goals/{g['id']}", headers=h).json()["id"] == g["id"]


def test_validation(client, sample_pdf):
    h = _signup(client, "goal-v@example.com")
    doc = _upload(client, h, sample_pdf)
    base = {"goal_type": "learn", "title": "x", "deadline": (_today() + timedelta(days=5)).isoformat(), "document_ids": [doc["id"]]}
    assert client.post("/api/goals", headers=h, json={**base, "minutes_per_day": 5}).status_code == 422
    assert client.post("/api/goals", headers=h, json={**base, "minutes_per_day": 500}).status_code == 422
    assert client.post("/api/goals", headers=h, json={**base, "minutes_per_day": 30, "study_days": [7]}).status_code == 422
    past = {**base, "minutes_per_day": 30, "deadline": (_today() - timedelta(days=1)).isoformat()}
    assert client.post("/api/goals", headers=h, json=past).status_code == 422
    assert client.post("/api/goals", headers=h, json={**base, "minutes_per_day": 30, "document_ids": []}).status_code == 422


def test_infeasible_goal_warns_and_never_exceeds_budget(client, sample_pdf):
    h = _signup(client, "goal-f@example.com")
    doc = _upload(client, h, sample_pdf)
    g = _goal(client, h, doc["id"], minutes_per_day=10, deadline=_today().isoformat())
    assert all(v <= 10 for v in _daily(g["items"]).values())
    assert g["feasibility_warning"] and "Left out" in g["feasibility_warning"]


def test_item_edit_regenerate_keeps_edits(client, sample_pdf):
    h = _signup(client, "goal-e@example.com")
    doc = _upload(client, h, sample_pdf)
    g = _goal(client, h, doc["id"])
    item = g["items"][-1]

    # status-only change does not mark the item as user-edited
    r = client.patch(f"/api/plan-items/{g['items'][0]['id']}", headers=h, json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done" and r.json()["user_edited"] is False

    new_date = (_today() + timedelta(days=2)).isoformat()
    r = client.patch(f"/api/plan-items/{item['id']}", headers=h, json={"scheduled_date": new_date, "estimated_minutes": 12})
    assert r.status_code == 200, r.text
    assert r.json()["user_edited"] is True and r.json()["scheduled_date"] == new_date
    too_late = (_today() + timedelta(days=60)).isoformat()
    assert client.patch(f"/api/plan-items/{item['id']}", headers=h, json={"scheduled_date": too_late}).status_code == 422

    added = client.post(f"/api/goals/{g['id']}/items", headers=h, json={
        "topic": "My own reading", "activity_type": "learn", "scheduled_date": new_date, "estimated_minutes": 10})
    assert added.status_code == 201 and added.json()["user_edited"] is True

    r = client.post(f"/api/goals/{g['id']}/regenerate", headers=h, json={})
    assert r.status_code == 200, r.text
    regen = r.json()
    by_id = {i["id"]: i for i in regen["items"]}
    assert by_id[item["id"]]["scheduled_date"] == new_date and by_id[item["id"]]["estimated_minutes"] == 12
    assert added.json()["id"] in by_id
    assert by_id[g["items"][0]["id"]]["status"] == "done"  # history kept
    assert all(v <= 45 for d, v in _daily(regen["items"]).items() if d >= _today().isoformat())
    assert [i["position"] for i in regen["items"]] == list(range(len(regen["items"])))

    # PATCH goal schedule fields replans without dropping edits
    r = client.patch(f"/api/goals/{g['id']}", headers=h, json={"minutes_per_day": 60, "title": "Renamed"})
    assert r.status_code == 200 and r.json()["title"] == "Renamed" and r.json()["minutes_per_day"] == 60
    assert any(i["id"] == item["id"] for i in r.json()["items"])

    assert client.delete(f"/api/plan-items/{added.json()['id']}", headers=h).status_code == 204
    assert all(i["id"] != added.json()["id"] for i in client.get(f"/api/goals/{g['id']}", headers=h).json()["items"])


def test_today_and_adapt_flow(client, sample_pdf):
    h = _signup(client, "goal-t@example.com")
    doc = _upload(client, h, sample_pdf)
    g = _goal(client, h, doc["id"])
    today = client.get("/api/today", headers=h).json()
    assert today["date"] == _today().isoformat()
    assert today["items"] and all(i["goal_id"] == g["id"] and i["goal_title"] == g["title"] for i in today["items"])
    assert today["total_minutes"] == sum(i["estimated_minutes"] for i in today["items"])

    # ahead of schedule: nothing to propose
    assert client.post(f"/api/goals/{g['id']}/adapt", headers=h).json() is None

    # a session the user put in the past and didn't do -> a move proposal
    yesterday = (_today() - timedelta(days=1)).isoformat()
    target = g["items"][1]
    assert client.patch(f"/api/plan-items/{target['id']}", headers=h, json={"scheduled_date": yesterday}).status_code == 200
    p = client.post(f"/api/goals/{g['id']}/adapt", headers=h).json()
    assert p and p["status"] == "pending" and p["reason"] and p["changes"]
    ch = next(c for c in p["changes"] if c["item_id"] == target["id"])
    assert ch["op"] in ("move", "remove") and ch["why"]
    assert client.get(f"/api/goals/{g['id']}", headers=h).json()["pending_proposal"]["id"] == p["id"]

    accepted = client.post(f"/api/plan-proposals/{p['id']}/accept", headers=h)
    assert accepted.status_code == 200, accepted.text
    out = accepted.json()
    assert out["pending_proposal"] is None
    if ch["op"] == "move":
        moved = next(i for i in out["items"] if i["id"] == target["id"])
        assert moved["scheduled_date"] == ch["to_date"]
    assert client.post(f"/api/plan-proposals/{p['id']}/accept", headers=h).status_code == 409

    # reject leaves the plan unchanged
    other = next(i for i in out["items"] if i["status"] == "pending" and i["scheduled_date"] >= _today().isoformat())
    assert client.patch(f"/api/plan-items/{other['id']}", headers=h, json={"scheduled_date": yesterday}).status_code == 200
    p2 = client.post(f"/api/goals/{g['id']}/adapt", headers=h).json()
    assert p2 and p2["status"] == "pending"
    before = client.get(f"/api/goals/{g['id']}", headers=h).json()["items"]
    after = client.post(f"/api/plan-proposals/{p2['id']}/reject", headers=h).json()
    assert after["items"] == before and after["pending_proposal"] is None

    # paused goals drop out of today
    client.patch(f"/api/goals/{g['id']}", headers=h, json={"status": "paused"})
    assert client.get("/api/today", headers=h).json()["items"] == []


def test_cross_user_isolation_goals(client, sample_pdf):
    owner = _signup(client, "goal-owner@example.com")
    intruder = _signup(client, "goal-intruder@example.com")
    doc = _upload(client, owner, sample_pdf)
    g = _goal(client, owner, doc["id"])
    iid = g["items"][0]["id"]
    yesterday = (_today() - timedelta(days=1)).isoformat()
    client.patch(f"/api/plan-items/{g['items'][1]['id']}", headers=owner, json={"scheduled_date": yesterday})
    p = client.post(f"/api/goals/{g['id']}/adapt", headers=owner).json()
    assert p

    for method, url, kw in [
        ("get", f"/api/goals/{g['id']}", {}),
        ("patch", f"/api/goals/{g['id']}", {"json": {"title": "hacked"}}),
        ("post", f"/api/goals/{g['id']}/regenerate", {"json": {}}),
        ("post", f"/api/goals/{g['id']}/items", {"json": {"topic": "x", "activity_type": "learn",
                                                           "scheduled_date": _today().isoformat(), "estimated_minutes": 10}}),
        ("post", f"/api/goals/{g['id']}/adapt", {}),
        ("patch", f"/api/plan-items/{iid}", {"json": {"status": "done"}}),
        ("delete", f"/api/plan-items/{iid}", {}),
        ("post", f"/api/plan-proposals/{p['id']}/accept", {}),
        ("post", f"/api/plan-proposals/{p['id']}/reject", {}),
        ("delete", f"/api/goals/{g['id']}", {}),
        ("post", "/api/goals", {"json": {"goal_type": "learn", "title": "x", "deadline": _today().isoformat(),
                                         "minutes_per_day": 30, "document_ids": [doc["id"]]}}),
    ]:
        r = getattr(client, method)(url, headers=intruder, **kw)
        assert r.status_code == 404, (method, url, r.status_code)
    assert client.get("/api/goals", headers=intruder).json() == []
    assert client.get("/api/today", headers=intruder).json()["items"] == []
    assert client.get(f"/api/goals/{g['id']}", headers=owner).json()["title"] == g["title"]

    assert client.delete(f"/api/goals/{g['id']}", headers=owner).status_code == 204
    assert client.get(f"/api/goals/{g['id']}", headers=owner).status_code == 404


def test_goals_require_auth(client):
    assert client.get("/api/goals").status_code == 401
    assert client.get("/api/today").status_code == 401


# UTC+14 and UTC-11 are 25 hours apart, so at any moment at least one of them is on a
# different date from the server (and from UTC): the old bug fails here whenever CI runs.
@pytest.mark.parametrize("tz", ["Pacific/Kiritimati", "Pacific/Pago_Pago"])
def test_plan_and_today_use_the_users_calendar_day(client, sample_pdf, tz):
    """Regression: the planner scheduled by the server's date while Today looked up items by
    UTC date, so a plan made near midnight had nothing to do "today". Both follow X-Timezone."""
    h = {**_signup(client, "tz@example.com"), "X-Timezone": tz}
    local_today = datetime.now(ZoneInfo(tz)).date()
    doc = _upload(client, h, sample_pdf)
    g = _goal(client, h, doc["id"], deadline=(local_today + timedelta(days=21)).isoformat())
    assert min(i["scheduled_date"] for i in g["items"]) == local_today.isoformat()

    steps = client.get("/api/today/preview", headers=h).json()["suggestions"]["30"]
    assert any(s["kind"] == "plan_item" for s in steps), steps
