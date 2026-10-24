"""Share a prep plan as a read-only link (P3: "shareable prep plan").

What a link shows: the role title and company, the interview date, the plan steps, and each
skill's name, priority and status. What it never shows: the resume or its quotes, the job ad
text, documents, answers, scores, the owner's name or email. Links expire (30 days by default),
can be revoked, and only the SHA-256 of the token is stored, so a database leak can't open them.
The public read runs in the system context (it has no user) and looks the link up by hash only.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models_interview import JobProfile, RolePrep
from ..models_share import PlanShare

TTL_DAYS = 30
MAX_ACTIVE_PER_PREP = 5


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def create(db: Session, owner_id: str, prep: RolePrep, now: datetime | None = None) -> tuple[PlanShare, str]:
    now = now or datetime.now(timezone.utc)
    active = [s for s in list_active(db, owner_id, prep.id, now)]
    for old in active[MAX_ACTIVE_PER_PREP - 1:]:  # keep the newest few
        old.revoked_at = now
    token = secrets.token_urlsafe(24)
    share = PlanShare(owner_id=owner_id, prep_id=prep.id, token_hash=_hash(token),
                      expires_at=now + timedelta(days=TTL_DAYS), views=0)
    db.add(share)
    db.flush()
    return share, token


def list_active(db: Session, owner_id: str, prep_id: str, now: datetime | None = None) -> list[PlanShare]:
    now = now or datetime.now(timezone.utc)
    rows = db.scalars(select(PlanShare).where(PlanShare.owner_id == owner_id, PlanShare.prep_id == prep_id,
                                              PlanShare.revoked_at.is_(None)).order_by(PlanShare.created_at.desc())).all()
    return [r for r in rows if _aware(r.expires_at) > now]


def revoke(db: Session, owner_id: str, share_id: str) -> bool:
    s = db.scalar(select(PlanShare).where(PlanShare.id == share_id, PlanShare.owner_id == owner_id))
    if s is None:
        return False
    s.revoked_at = s.revoked_at or datetime.now(timezone.utc)
    return True


def public_view(db: Session, token: str, now: datetime | None = None) -> dict | None:
    """The shared plan, or None for an unknown, revoked or expired link. Counts the view."""
    now = now or datetime.now(timezone.utc)
    if not token or len(token) > 64:
        return None
    s = db.scalar(select(PlanShare).where(PlanShare.token_hash == _hash(token)))
    if s is None or s.revoked_at is not None or _aware(s.expires_at) <= now:
        return None
    prep = db.get(RolePrep, s.prep_id)
    if prep is None:
        return None
    job = db.get(JobProfile, prep.job_id)
    s.views += 1
    names = {k.competency_id: k.name for k in prep.skills}
    return {
        "role_title": job.role_title if job else "",
        "company": job.company if job else None,
        "interview_date": prep.interview_date.isoformat() if prep.interview_date else None,
        "plan": [{"title": p.get("title", ""), "activity": p.get("activity", ""),
                  "estimated_minutes": int(p.get("estimated_minutes") or 0), "reason": p.get("reason", ""),
                  "skill": names.get(p.get("competency_id"))} for p in (prep.plan or [])],
        "skills": [{"name": k.name, "priority": (k.user_override or {}).get("priority") or k.priority,
                    "status": k.gap_type} for k in sorted(prep.skills, key=lambda k: k.rank)],
        "expires_at": _aware(s.expires_at).isoformat(),
    }
