"""Product events, the activation metric and onboarding experiments (docs/ux-research.md).

Content-free by construction: an event is a name from EVENTS plus properties from that
event's allowlist, each a bool, a small int or a short enum-like string. Anything else is
dropped before it is stored, so a careless call can't log a question or a filename.

Activation (ux-research "agree on what activated means"): the first time either
  * gap_report  — the user has a gap report on their own resume and a real job, or
  * learning    — the user got a verified (or partly verified) cited answer and answered a question.
Recorded once as an `activated` event with the path and seconds since sign-up.

Experiments: a user's variant is a stable hash of (experiment, user id), so it needs no
storage and never flips. `EXPERIMENT_ONBOARDING` = on (50/50, default) | off (everyone gets
goal_first, the control) | goal_first | upload_first (force one, e.g. after a decision).
Exposure is recorded when the onboarding is actually shown (client event).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User
from ..models_analytics import ProductEvent

log = logging.getLogger("mindmesh.analytics")

EXPERIMENTS: dict[str, tuple[str, ...]] = {"onboarding": ("goal_first", "upload_first")}

_ENUM = re.compile(r"^[a-z0-9_]{1,40}$")
# event -> allowed property names. Values: bool, int (0..10^7) or a short lowercase token.
EVENTS: dict[str, set[str]] = {
    "signed_up": {"method"},
    "onboarding_shown": {"experiment", "variant"},
    "onboarding_choice": {"variant", "choice"},
    "document_uploaded": set(),
    "tutor_answer": {"status"},
    "quiz_created": {"count"},
    "question_answered": {"qtype"},
    "gap_report_ready": {"source"},
    "session_completed": {"minutes"},
    "activated": {"path", "seconds"},
    "plan_shared": set(),
    "voice_answer": {"seconds", "wpm", "fillers"},
    "notes_answer": {"mode"},
}
CLIENT_EVENTS = {"onboarding_shown", "onboarding_choice", "voice_answer"}  # the only ones the browser may send


def clean_props(name: str, props: dict | None) -> dict:
    allowed = EVENTS.get(name, set())
    out: dict = {}
    for k, v in (props or {}).items():
        if k not in allowed:
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, int) and 0 <= v <= 10_000_000:
            out[k] = v
        elif isinstance(v, str) and _ENUM.match(v):
            out[k] = v
    return out


def track(db: Session, owner_id: str, name: str, props: dict | None = None, *, commit: bool = False) -> None:
    """Record an event. Unknown names are ignored (logged): analytics must never break a request."""
    if name not in EVENTS:
        log.warning("unknown product event %s ignored", name)
        return
    db.add(ProductEvent(owner_id=owner_id, name=name, props=clean_props(name, props)))
    db.flush()  # visible to the activation check (sessions don't autoflush)
    if commit:
        db.commit()


# ---------------------------------------------------------------- experiments

def variant(experiment: str, user_id: str, mode: str | None = None) -> str:
    from ..config import get_settings

    arms = EXPERIMENTS[experiment]
    mode = (mode if mode is not None else get_settings().experiment_onboarding).strip().lower()
    if mode in arms:
        return mode
    if mode == "off":
        return arms[0]  # the control
    h = int(hashlib.sha256(f"{experiment}:{user_id}".encode()).hexdigest()[:8], 16)
    return arms[h % len(arms)]


# ---------------------------------------------------------------- activation

def _has(db: Session, owner_id: str, name: str, **props) -> bool:
    rows = db.scalars(select(ProductEvent.props).where(ProductEvent.owner_id == owner_id, ProductEvent.name == name)).all()
    return any(all(p.get(k) in v if isinstance(v, (tuple, set)) else p.get(k) == v for k, v in props.items()) for p in rows)


def check_activation(db: Session, user: User, now: datetime | None = None) -> str | None:
    """Record `activated` the first time a path is complete. Returns the path when it fires now."""
    if _has(db, user.id, "activated"):
        return None
    if _has(db, user.id, "gap_report_ready"):
        path = "gap_report"
    elif _has(db, user.id, "tutor_answer", status=("verified", "partial")) and _has(db, user.id, "question_answered"):
        path = "learning"
    else:
        return None
    now = now or datetime.now(timezone.utc)
    created = user.created_at if user.created_at.tzinfo else user.created_at.replace(tzinfo=timezone.utc)
    seconds = max(0, int((now - created).total_seconds()))
    track(db, user.id, "activated", {"path": path, "seconds": min(seconds, 10_000_000)})
    return path


def record(db: Session, user: User, name: str, props: dict | None = None) -> None:
    """track + activation check + commit, swallowing errors: the caller's work is already done."""
    try:
        track(db, user.id, name, props)
        check_activation(db, user)
        db.commit()
    except Exception:  # noqa: BLE001 - analytics must never fail the request it describes
        db.rollback()
        log.exception("product event %s not recorded", name)


# ---------------------------------------------------------------- experiment report

WINDOWS = (("3 min", 180), ("1 day", 86_400), ("7 days", 7 * 86_400))


def two_proportion_p(x1: int, n1: int, x2: int, n2: int) -> float | None:
    """Two-sided p-value of a two-proportion z-test; None when it isn't meaningful."""
    import math

    if min(n1, n2) == 0:
        return None
    p = (x1 + x2) / (n1 + n2)
    if p in (0.0, 1.0):
        return None
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    z = (x1 / n1 - x2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def _returned_within(db: Session, users: list[str], days: int = 7) -> set[str]:
    """Users with any product event on a later day than sign-up, within `days` of it (retention)."""
    from datetime import timedelta

    if not users:
        return set()
    signup = {u: c for u, c in db.execute(select(User.id, User.created_at).where(User.id.in_(users)))}
    out: set[str] = set()
    for owner, at in db.execute(select(ProductEvent.owner_id, ProductEvent.created_at).where(ProductEvent.owner_id.in_(users))):
        start = signup.get(owner)
        if start is None:
            continue
        start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        if start + timedelta(hours=20) <= at <= start + timedelta(days=days):
            out.add(owner)
    return out


def experiment_summary(db: Session, experiment: str = "onboarding", since: datetime | None = None) -> dict:
    """Per arm: users exposed, and how many activated within each window of signing up. Counts only."""
    q = select(ProductEvent.owner_id, ProductEvent.props, ProductEvent.created_at).where(ProductEvent.name == "onboarding_shown")
    if since is not None:
        q = q.where(ProductEvent.created_at >= since)
    arm_of: dict[str, str] = {}
    for owner, props, _ in sorted(db.execute(q).all(), key=lambda r: r[2]):
        if props.get("experiment") == experiment and owner not in arm_of:
            arm_of[owner] = props.get("variant", "")  # first exposure wins
    seconds: dict[str, int] = {}
    for owner, props in db.execute(select(ProductEvent.owner_id, ProductEvent.props)
                                   .where(ProductEvent.name == "activated", ProductEvent.owner_id.in_(list(arm_of) or [""]))):
        seconds[owner] = int(props.get("seconds", 10**9))
    returned = _returned_within(db, list(arm_of), days=7)
    arms = {}
    for arm in EXPERIMENTS[experiment]:
        users = [u for u, a in arm_of.items() if a == arm]
        arms[arm] = {"exposed": len(users),
                     **{label: sum(1 for u in users if seconds.get(u, 10**9) <= secs) for label, secs in WINDOWS},
                     "returned 7d": sum(1 for u in users if u in returned)}
    a, b = EXPERIMENTS[experiment]
    p_values = {label: two_proportion_p(arms[a][label], arms[a]["exposed"], arms[b][label], arms[b]["exposed"])
                for label in [w for w, _ in WINDOWS] + ["returned 7d"]}
    return {"experiment": experiment, "arms": arms, "p_values": p_values}
