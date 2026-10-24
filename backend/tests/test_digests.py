"""Reminder and weekly-summary emails (app/services/digests.py, app/mailer.py, unsubscribe)."""
import dataclasses
import smtplib
import time
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import mailer
from app.config import get_settings
from app.mailer import Email, EmailError
from app.services import digests
from app.services.digests import (Situation, in_quiet_hours, reminder_due, run_due, unsubscribe_token,
                                  user_from_unsubscribe_token, weekly_due)

KOL = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------- pure rules

@pytest.mark.parametrize("now, start, end, quiet", [
    ("22:30", "21:00", "08:00", True), ("07:59", "21:00", "08:00", True), ("08:00", "21:00", "08:00", False),
    ("18:30", "21:00", "08:00", False), ("13:00", "12:00", "14:00", True), ("14:00", "12:00", "14:00", False),
    ("10:00", "09:00", "09:00", False),
])
def test_quiet_hours(now, start, end, quiet):
    h, m = map(int, now.split(":"))
    assert in_quiet_hours(dtime(h, m), start, end) is quiet


def _sit(**over):
    base = dict(local_now=datetime(2026, 10, 19, 18, 30, tzinfo=KOL), reminders_on=True, quiet_start="21:00",
                quiet_end="08:00", practised_today=False, ready_count=2, sent_today=frozenset())
    base.update(over)
    return Situation(**base)


@pytest.mark.parametrize("over, due", [
    ({}, True),
    ({"reminders_on": False}, False),
    ({"sent_today": frozenset({"reminder"})}, False),
    ({"practised_today": True}, False),
    ({"ready_count": 0}, False),
    ({"local_now": datetime(2026, 10, 19, 17, 59, tzinfo=KOL)}, False),
    ({"local_now": datetime(2026, 10, 19, 22, 0, tzinfo=KOL)}, False),  # quiet hours
])
def test_reminder_rules(over, due):
    assert reminder_due(_sit(**over), hour=18) is due


def test_weekly_only_on_monday_after_the_hour():
    monday = datetime(2026, 10, 19, 9, 30, tzinfo=KOL)  # 19 Oct 2026 is a Monday
    assert weekly_due(_sit(local_now=monday), hour=9)
    assert not weekly_due(_sit(local_now=monday - timedelta(hours=1)), hour=9)
    assert not weekly_due(_sit(local_now=monday + timedelta(days=1)), hour=9)
    assert not weekly_due(_sit(local_now=monday, sent_today=frozenset({"weekly"})), hour=9)


def test_unsubscribe_tokens():
    t = unsubscribe_token("user123")
    assert user_from_unsubscribe_token(t) == "user123"
    assert user_from_unsubscribe_token(t.replace("user123", "user999")) is None  # can't retarget
    assert user_from_unsubscribe_token(t[:-2] + "xx") is None
    assert user_from_unsubscribe_token("") is None


# ---------------------------------------------------------------- end to end (console backend in tests)

@pytest.fixture
def outbox(monkeypatch):
    sent: list[Email] = []
    monkeypatch.setattr(digests, "send", lambda e: sent.append(e) or True)
    return sent


def _user_with_plan_today(client, sample_pdf, email="reader@example.com", reminders=True):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    h = {"Authorization": f"Bearer {r.json()['token']}", "X-Timezone": "Asia/Kolkata"}
    assert client.get("/api/me/prefs", headers=h).json()  # remembers the timezone
    client.patch("/api/me/prefs", headers=h, json={"reminders": reminders})
    doc = client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": ("a.pdf", sample_pdf, "application/pdf")}).json()
    for _ in range(50):
        if client.get(f"/api/documents/{doc['id']}", headers=h).json()["status"] == "ready":
            break
        time.sleep(0.05)
    deadline = (datetime.now(KOL).date() + timedelta(days=14)).isoformat()
    g = client.post("/api/goals", headers=h, json={"goal_type": "learn", "title": "Factory physics", "deadline": deadline,
                                                  "minutes_per_day": 30, "study_days": list(range(7)), "document_ids": [doc["id"]]})
    assert g.status_code == 201, g.text
    return h, doc


def _local(hour, minute=0, days=0):
    d = datetime.now(KOL) + timedelta(days=days)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(timezone.utc)


def test_reminder_goes_out_once_in_the_users_evening_without_content(client, sample_pdf, outbox):
    _user_with_plan_today(client, sample_pdf)
    assert run_due(_local(17, 30))["reminder"] == 0, "before 18:00 local"
    assert run_due(_local(18, 30))["reminder"] == 1
    assert run_due(_local(19, 0))["reminder"] == 0, "once per day"
    reminders = [m for m in outbox if m.subject == "Your Mindmesh session for today"]  # on a Monday the weekly one goes too
    assert len(reminders) == 1
    e = reminders[0]
    assert e.to == "reader@example.com"
    assert "Little" not in e.text and "Variability" not in e.text, "no document content in email"
    assert e.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "/api/email/unsubscribe?token=" in e.headers["List-Unsubscribe"]


def test_practice_just_after_local_midnight_counts_for_that_day(client, sample_pdf, outbox):
    """00:30 in Kolkata is 19:00 UTC the day before: it still counts as practising on the local day."""
    from app.db import SessionLocal
    from app.models import Attempt

    h, doc = _user_with_plan_today(client, sample_pdf, email="early@example.com")
    quiz = client.post("/api/quizzes", headers=h, json={"document_ids": [doc["id"]], "count": 3}).json()
    q = quiz["questions"][0]
    body = {"selected_index": 0} if q["qtype"] == "mcq" else {"answer_text": "x"}
    assert client.post(f"/api/questions/{q['id']}/attempts", headers=h, json=body).status_code == 201
    with SessionLocal() as db:
        for a in db.query(Attempt).all():
            a.created_at = _local(0, 30)
        db.commit()
    assert run_due(_local(18, 30))["reminder"] == 0
    week = client.get("/api/week", headers=h)  # the Today week row agrees
    assert week.status_code == 200, week.text
    today = datetime.now(KOL).date().isoformat()
    assert any(d["date"] == today and d["practised"] for d in week.json()["days"]), week.json()


def test_no_reminder_when_off_or_already_practised(client, sample_pdf, outbox):
    _user_with_plan_today(client, sample_pdf, email="quiet@example.com", reminders=False)
    h, doc = _user_with_plan_today(client, sample_pdf, email="busy@example.com")
    quiz = client.post("/api/quizzes", headers=h, json={"document_ids": [doc["id"]], "count": 3}).json()
    q = quiz["questions"][0]
    body = {"selected_index": 0} if q["qtype"] == "mcq" else {"answer_text": "x"}
    assert client.post(f"/api/questions/{q['id']}/attempts", headers=h, json=body).status_code == 201
    assert run_due(_local(18, 30))["reminder"] == 0
    assert [m for m in outbox if m.subject == "Your Mindmesh session for today"] == []


def test_weekly_summary_on_monday_morning(client, sample_pdf, outbox):
    _user_with_plan_today(client, sample_pdf, email="weekly@example.com")
    today = datetime.now(KOL).date()
    days_to_monday = (7 - today.weekday()) % 7 or 7
    c = run_due(_local(9, 30, days=days_to_monday))
    assert c["weekly"] == 1
    e = next(x for x in outbox if x.subject == "Your week in Mindmesh")
    assert "target days" in e.text and "Little" not in e.text


def test_failed_send_is_retried_next_tick(client, sample_pdf, monkeypatch):
    _user_with_plan_today(client, sample_pdf, email="retry@example.com")
    calls = []

    def flaky(e):
        calls.append(e)
        if len(calls) == 1:
            raise EmailError("smtp down")
        return True

    monkeypatch.setattr(digests, "send", flaky)
    assert run_due(_local(18, 30))["reminder"] == 0
    assert run_due(_local(18, 35))["reminder"] == 1, "nothing recorded for the failed attempt, so it retries"


def test_one_click_unsubscribe(client, sample_pdf, outbox):
    h, _ = _user_with_plan_today(client, sample_pdf, email="leave@example.com")
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    token = unsubscribe_token(uid)
    assert client.post(f"/api/email/unsubscribe?token={token}").status_code == 200
    assert client.get("/api/me/prefs", headers=h).json()["reminders"] is False
    assert run_due(_local(18, 30))["reminder"] == 0
    page = client.get(f"/api/email/unsubscribe?token={token}")
    assert page.status_code == 200 and "Reminders are off" in page.text
    assert client.post("/api/email/unsubscribe?token=forged.token").status_code == 400


# ---------------------------------------------------------------- SMTP transport

def test_smtp_backend_builds_a_proper_message(monkeypatch):
    s = dataclasses.replace(get_settings(), email_backend="smtp", smtp_host="smtp.example.com", smtp_port=587,
                            smtp_username="apikey", smtp_password="secret", smtp_security="starttls",
                            email_from="Mindmesh <hello@mindmesh.app>")
    monkeypatch.setattr(mailer, "get_settings", lambda: s)
    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            seen["addr"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context):
            seen["tls"] = True

        def login(self, u, p):
            seen["login"] = (u, p)

        def send_message(self, msg):
            seen["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    assert mailer.send(Email(to="a@example.com", subject="Hi", text="plain", html="<p>html</p>",
                             headers={"List-Unsubscribe": "<https://x/u>"}))
    m = seen["msg"]
    assert seen["addr"] == ("smtp.example.com", 587) and seen["tls"] and seen["login"] == ("apikey", "secret")
    assert m["From"] == "Mindmesh <hello@mindmesh.app>" and m["List-Unsubscribe"] == "<https://x/u>"
    assert m.get_body(("plain",)).get_content().strip() == "plain" and m.get_body(("html",)) is not None

    def broken(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", broken)
    with pytest.raises(EmailError):
        mailer.send(Email(to="a@example.com", subject="Hi", text="plain"))


def test_email_off_sends_nothing(monkeypatch):
    s = dataclasses.replace(get_settings(), email_backend="off")
    monkeypatch.setattr(digests, "get_settings", lambda: s)
    assert run_due() == {"reminder": 0, "weekly": 0, "checked": 0}
