"""Goals and study plans (PRD FR-020..023, 12.1). Owned by workstream D; schema frozen by CONTRACTS.md."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import _now, _uuid


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    goal_type: Mapped[str] = mapped_column(String(12))  # learn | revise | exam | interview
    title: Mapped[str] = mapped_column(String(255))
    target_outcome: Mapped[str] = mapped_column(Text, default="")
    deadline: Mapped[date] = mapped_column(Date)
    minutes_per_day: Mapped[int] = mapped_column(Integer)
    study_days: Mapped[list] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])  # Mon=0
    current_level: Mapped[str] = mapped_column(String(20), default="standard")
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    prep_id: Mapped[str | None] = mapped_column(ForeignKey("role_preps.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | paused | completed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    items: Mapped[list[PlanItem]] = relationship(cascade="all, delete-orphan", passive_deletes=True, order_by="PlanItem.position")


class PlanItem(Base):
    __tablename__ = "plan_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)
    topic: Mapped[str] = mapped_column(String(255))
    concept: Mapped[str | None] = mapped_column(String(120), nullable=True)
    activity_type: Mapped[str] = mapped_column(String(16))  # learn | practice | review | mock_interview | drill
    estimated_minutes: Mapped[int] = mapped_column(Integer)
    objective: Mapped[str] = mapped_column(Text, default="")
    source_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | done | skipped
    user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlanProposal(Base):
    """A suggested plan change the user must accept or reject (FR-023)."""
    __tablename__ = "plan_proposals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    changes: Mapped[list] = mapped_column(JSON, default=list)  # ProposalChange[]
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | accepted | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
