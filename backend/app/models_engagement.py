"""Engagement: weekly targets, timed sessions, onboarding, interview debriefs (UX research).

Schema frozen by docs/CONTRACTS.md §7. Owned by workstream W2.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import _now, _uuid


class UserPrefs(Base):
    """One row per user. Created lazily on first read."""
    __tablename__ = "user_prefs"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    preparing_for: Mapped[str | None] = mapped_column(String(12), nullable=True)  # interview | exam | learn
    weekly_target: Mapped[int] = mapped_column(Integer, default=3)  # sessions per week, 1..7
    default_minutes: Mapped[int] = mapped_column(Integer, default=15)  # 5 | 15 | 30
    reminders: Mapped[bool] = mapped_column(default=False)
    quiet_start: Mapped[str] = mapped_column(String(5), default="21:00")
    quiet_end: Mapped[str] = mapped_column(String(5), default="08:00")
    reduce_transparency: Mapped[bool] = mapped_column(default=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)  # last IANA zone the browser sent
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class StudySession(Base):
    """A timed Today session (5/15/30 min) made of a few steps."""
    __tablename__ = "study_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    minutes: Mapped[int] = mapped_column(Integer)
    steps: Mapped[list] = mapped_column(JSON, default=list)  # SessionStep[]
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | completed | abandoned
    wins: Mapped[list] = mapped_column(JSON, default=list)  # Win[] computed on completion
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InterviewDebrief(Base):
    """'How did it go?' after the interview date (UX research: plan for the end of the deadline)."""
    __tablename__ = "interview_debriefs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    prep_id: Mapped[str] = mapped_column(ForeignKey("role_preps.id", ondelete="CASCADE"), index=True)
    outcome: Mapped[str] = mapped_column(String(16))  # offer | next_round | rejected | not_happened | prefer_not
    note: Mapped[str] = mapped_column(Text, default="")
    next_step: Mapped[str | None] = mapped_column(String(16), nullable=True)  # next_round | new_role | learning_goal | none
    interview_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EmailLog(Base):
    """One row per email sent: the unique key makes each kind go out at most once per user-local day."""
    __tablename__ = "email_log"
    __table_args__ = (UniqueConstraint("owner_id", "kind", "local_date", name="uq_email_log_owner_kind_date"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # reminder | weekly
    local_date: Mapped[date] = mapped_column(Date)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
