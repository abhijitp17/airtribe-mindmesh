"""Reminder and weekly-summary emails (Wave 4, UX research: useful nudges, never guilt).

Only users who turned reminders on get either email. Times are the user's own (the last
timezone their browser sent), never inside their quiet hours:
  * daily reminder: from REMINDER_LOCAL_HOUR (18:00), only if nothing practised yet today and
    something is ready (a due review or today's plan item);
  * weekly summary: Monday from WEEKLY_SUMMARY_LOCAL_HOUR (09:00): last week's practice days
    against the target, and what's planned this week.
Emails carry counts and links only: no topic names or document text, since mail passes
through third parties. email_log makes each kind go out at most once per user-local day,
however many workers run. run_due() is called by worker.py every few minutes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..clock import parse_tz, user_tz
from ..config import get_settings
from ..mailer import Email, EmailError, send
from ..models import User
from ..models_engagement import EmailLog, UserPrefs
from ..models_goals import Goal, PlanItem
from .. import push
from ..push import PushMessage
from . import engagement as eng

log = logging.getLogger("mindmesh.digests")


# ---------------------------------------------------------------- pure decisions

def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_quiet_hours(now: time, start: str, end: str) -> bool:
    """Quiet window [start, end); it may wrap midnight (21:00-08:00)."""
    a, b = _hm(start), _hm(end)
    if a == b:
        return False
    return (a <= now < b) if a < b else (now >= a or now < b)


@dataclass(frozen=True)
class Situation:
    local_now: datetime
    reminders_on: bool
    quiet_start: str
    quiet_end: str
    practised_today: bool
    ready_count: int
    sent_today: frozenset[str]


def reminder_due(s: Situation, hour: int) -> bool:
    return (s.reminders_on and "reminder" not in s.sent_today and not s.practised_today and s.ready_count > 0
            and s.local_now.hour >= hour and not in_quiet_hours(s.local_now.time(), s.quiet_start, s.quiet_end))


def weekly_due(s: Situation, hour: int) -> bool:
    return (s.reminders_on and "weekly" not in s.sent_today and s.local_now.weekday() == 0
            and s.local_now.hour >= hour and not in_quiet_hours(s.local_now.time(), s.quiet_start, s.quiet_end))


# ---------------------------------------------------------------- unsubscribe links

def unsubscribe_token(user_id: str) -> str:
    sig = hmac.new(get_settings().email_token_secret.encode(), f"unsubscribe:{user_id}".encode(), hashlib.sha256).digest()
    return f"{user_id}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"


def user_from_unsubscribe_token(token: str) -> str | None:
    user_id, _, _sig = (token or "").partition(".")
    if not user_id or not hmac.compare_digest(unsubscribe_token(user_id), token):
        return None
    return user_id


# ---------------------------------------------------------------- messages

def _footer(user_id: str) -> tuple[str, str, dict[str, str]]:
    s = get_settings()
    one_click = f"{s.api_public_url}/api/email/unsubscribe?token={quote(unsubscribe_token(user_id))}"
    text = (f"\n\nYou're getting this because reminders are on in Mindmesh.\n"
            f"Turn them off in Settings ({s.web_url}/settings) or with one click: {one_click}\n")
    html = (f'<p style="color:#56605B;font-size:13px">You\'re getting this because reminders are on in Mindmesh. '
            f'<a href="{s.web_url}/settings">Settings</a> · <a href="{one_click}">Turn reminders off</a></p>')
    headers = {"List-Unsubscribe": f"<{one_click}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return text, html, headers


def reminder_email(user: User, ready: int, minutes: int) -> Email:
    s = get_settings()
    things = "1 thing" if ready == 1 else f"{ready} things"
    body = f"You have {things} ready for today. A {minutes}-minute session covers the most useful one first."
    ft, fh, headers = _footer(user.id)
    return Email(
        to=user.email, subject="Your Mindmesh session for today",
        text=f"{body}\n\nStart now: {s.web_url}/{ft}",
        html=(f'<p style="font-size:16px;color:#1D2321">{body}</p>'
              f'<p><a href="{s.web_url}/" style="background:#F2621A;color:#1D2321;padding:10px 16px;border-radius:12px;'
              f'text-decoration:none;font-weight:500">Start a session</a></p>{fh}'),
        headers=headers,
    )


def weekly_email(user: User, done: int, target: int, planned: int) -> Email:
    s = get_settings()
    line1 = f"Last week you practised on {done} of your {target} target days."
    line2 = (f"This week your plan has {planned} session{'s' if planned != 1 else ''} lined up." if planned
             else "Nothing is planned this week yet. A short goal keeps the momentum going.")
    ft, fh, headers = _footer(user.id)
    return Email(
        to=user.email, subject="Your week in Mindmesh",
        text=f"{line1}\n{line2}\n\nOpen Mindmesh: {s.web_url}/{ft}",
        html=(f'<p style="font-size:16px;color:#1D2321">{line1}<br>{line2}</p>'
              f'<p><a href="{s.web_url}/">Open Mindmesh</a></p>{fh}'),
        headers=headers,
    )


# ---------------------------------------------------------------- runner

def _claim(db: Session, owner_id: str, kind: str, day: date) -> EmailLog | None:
    row = EmailLog(owner_id=owner_id, kind=kind, local_date=day)
    try:
        with db.begin_nested():
            db.add(row)
        return row
    except IntegrityError:  # another worker already sent it
        return None


def _push_for(email: Email) -> PushMessage:
    """The same message for the user's devices: counts only, no content (the email's first lines)."""
    first = email.text.split("\n\n", 1)[0].replace("\n", " ")
    return PushMessage(title=email.subject, body=first, data={"url": "/"})


def _deliver(db: Session, user: User, kind: str, day: date, email: Email) -> bool:
    """Email and/or push, at most once per kind per user-local day (the email_log claim covers both)."""
    row = _claim(db, user.id, kind, day)
    if row is None:
        return False
    sent = False
    try:
        sent = send(email)
    except EmailError as exc:
        log.warning("email %s for a user failed: %s", kind, exc)
    try:
        sent = push.send(db, user.id, _push_for(email)) > 0 or sent
    except push.PushError as exc:
        log.warning("push %s for a user failed: %s", kind, exc)
    if not sent:  # nothing went out (both off, or both failed): free the claim to retry on a later tick
        db.execute(delete(EmailLog).where(EmailLog.id == row.id))
    db.commit()
    return sent


def _planned_this_week(db: Session, user_id: str, today: date) -> int:
    return int(db.scalar(
        select(func.count()).select_from(PlanItem).join(Goal, Goal.id == PlanItem.goal_id)
        .where(PlanItem.owner_id == user_id, Goal.status == "active", PlanItem.status == "pending",
               PlanItem.scheduled_date >= today, PlanItem.scheduled_date < today + timedelta(days=7))
    ) or 0)


def run_due(now: datetime | None = None) -> dict[str, int]:
    """Send whatever is due right now. Safe to call often and from several workers at once."""
    from ..db import SessionLocal
    from ..jobs import system_context

    s = get_settings()
    now = now or datetime.now(timezone.utc)
    counts = {"reminder": 0, "weekly": 0, "checked": 0}
    if s.email_backend == "off" and s.push_backend == "off":
        return counts
    with system_context():  # reads every opted-in user (RLS bypass for trusted server code)
        db = SessionLocal()
        try:
            rows = db.execute(select(UserPrefs, User).join(User, User.id == UserPrefs.owner_id)
                              .where(UserPrefs.reminders.is_(True))).all()
            for prefs, user in rows:
                counts["checked"] += 1
                token = user_tz.set(parse_tz(prefs.timezone))
                try:
                    _run_user(db, user, prefs, now, counts)
                except Exception:  # noqa: BLE001 - one user's problem must not stop the others
                    db.rollback()
                    log.exception("digest failed for a user")
                finally:
                    user_tz.reset(token)
        finally:
            db.close()
    return counts


def _run_user(db: Session, user: User, prefs: UserPrefs, now: datetime, counts: dict[str, int]) -> None:
    s = get_settings()
    local_now = now.astimezone(user_tz.get())
    today = local_now.date()
    sent = frozenset(db.scalars(select(EmailLog.kind).where(EmailLog.owner_id == user.id, EmailLog.local_date == today)).all())
    practised = today in eng.practised_in_range(user.id, db, today, today + timedelta(days=1))
    inp = eng.builder_input(user.id, db, now)
    sit = Situation(local_now, bool(prefs.reminders), prefs.quiet_start, prefs.quiet_end, practised,
                    len(inp.due_reviews) + len(inp.plan_items), sent)
    if reminder_due(sit, s.reminder_hour):
        if _deliver(db, user, "reminder", today, reminder_email(user, sit.ready_count, prefs.default_minutes)):
            counts["reminder"] += 1
    if weekly_due(sit, s.weekly_hour):
        last_week = eng.week(user, db, today - timedelta(days=1))
        email = weekly_email(user, last_week["done"], last_week["target"], _planned_this_week(db, user.id, today))
        if _deliver(db, user, "weekly", today, email):
            counts["weekly"] += 1
