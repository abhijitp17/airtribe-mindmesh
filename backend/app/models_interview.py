"""Interview-prep persistence (PRD §7, 12.1). Owned by workstream B; schema frozen by CONTRACTS.md.

JSON column shapes are documented in docs/CONTRACTS.md (ResumeParsed, JobParsed,
Evaluation, ...). Resume claims are stored as claims, never as verified facts.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import _now, _uuid


class ResumeProfile(Base):
    __tablename__ = "resume_profiles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)  # ResumeParsed
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class JobProfile(Base):
    __tablename__ = "job_profiles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    role_title: Mapped[str] = mapped_column(String(255), default="")
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(60), nullable=True)
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)  # JobParsed
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class RolePrep(Base):
    """A resume x JD pairing the user is preparing for."""
    __tablename__ = "role_preps"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resume_profiles.id", ondelete="CASCADE"))
    job_id: Mapped[str] = mapped_column(ForeignKey("job_profiles.id", ondelete="CASCADE"))
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    interview_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    plan: Mapped[list] = mapped_column(JSON, default=list)  # PrepPlanItem[]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    skills: Mapped[list[SkillMatch]] = relationship(cascade="all, delete-orphan", passive_deletes=True, order_by="SkillMatch.rank")


class SkillMatch(Base):
    __tablename__ = "skill_matches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    prep_id: Mapped[str] = mapped_column(ForeignKey("role_preps.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    competency_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(20))
    jd_importance: Mapped[str] = mapped_column(String(10))
    resume_strength: Mapped[str] = mapped_column(String(10))
    resume_evidence: Mapped[list] = mapped_column(JSON, default=list)
    assessed_level: Mapped[str] = mapped_column(String(12), default="unverified")
    assessed_explanation: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String(8), default="low")
    gap_type: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(10))
    priority_factors: Mapped[dict] = mapped_column(JSON, default=dict)
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    linked_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    user_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    prep_id: Mapped[str] = mapped_column(ForeignKey("role_preps.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    focus: Mapped[str] = mapped_column(String(20), default="mixed")
    target_questions: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | completed
    rubric_version: Mapped[str] = mapped_column(String(80), default="")
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    turns: Mapped[list[InterviewTurn]] = relationship(cascade="all, delete-orphan", passive_deletes=True, order_by="InterviewTurn.position")


class InterviewTurn(Base):
    __tablename__ = "interview_turns"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))  # question | follow_up
    category: Mapped[str] = mapped_column(String(20))
    competency_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    competency_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Evaluation
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
