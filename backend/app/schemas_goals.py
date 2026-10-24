"""Request/response schemas for goals & plans (CONTRACTS §4)."""
from __future__ import annotations

from datetime import date, datetime
from datetime import date as Date  # alias: TodayOut has a field called `date`
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

GoalType = Literal["learn", "revise", "exam", "interview"]
GoalStatus = Literal["active", "paused", "completed"]
Activity = Literal["learn", "practice", "review", "mock_interview", "drill"]
ItemStatus = Literal["pending", "done", "skipped"]
LevelT = Literal["beginner", "standard", "advanced"]


def _clean_days(v: list[int] | None) -> list[int] | None:
    if v is None:
        return None
    days = sorted({int(d) for d in v})
    if not days or any(d < 0 or d > 6 for d in days):
        raise ValueError("study_days must contain at least one weekday number from 0 (Mon) to 6 (Sun)")
    return days


class GoalCreate(BaseModel):
    goal_type: GoalType
    title: str = Field(min_length=1, max_length=255)
    target_outcome: str = Field(default="", max_length=2000)
    deadline: date
    minutes_per_day: int = Field(ge=10, le=480)
    study_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], max_length=7)
    current_level: LevelT = "standard"
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    prep_id: str | None = None

    @field_validator("study_days")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int] | None:
        return _clean_days(v)


class GoalPatch(BaseModel):
    goal_type: GoalType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    target_outcome: str | None = Field(default=None, max_length=2000)
    deadline: date | None = None
    minutes_per_day: int | None = Field(default=None, ge=10, le=480)
    study_days: list[int] | None = Field(default=None, max_length=7)
    current_level: LevelT | None = None
    document_ids: list[str] | None = Field(default=None, max_length=20)
    prep_id: str | None = None
    status: GoalStatus | None = None

    @field_validator("study_days")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int] | None:
        return _clean_days(v)


class RegenerateIn(BaseModel):
    keep_edited: bool = True


class PlanItemPatch(BaseModel):
    scheduled_date: date | None = None
    estimated_minutes: int | None = Field(default=None, ge=5, le=480)
    topic: str | None = Field(default=None, min_length=1, max_length=255)
    status: ItemStatus | None = None
    position: int | None = Field(default=None, ge=0)


class PlanItemCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=255)
    activity_type: Activity
    scheduled_date: date
    estimated_minutes: int = Field(ge=5, le=480)


class SourceOut(BaseModel):
    chunk_id: str
    document_id: str
    page_start: int
    page_end: int
    section: str


class PlanItemOut(BaseModel):
    id: str
    position: int
    scheduled_date: date
    topic: str
    concept: str | None
    activity_type: Activity
    estimated_minutes: int
    objective: str
    sources: list[SourceOut]
    status: ItemStatus
    user_edited: bool
    reason: str


class PlanProposalOut(BaseModel):
    id: str
    reason: str
    # ProposalChange[]: {op, item_id, topic?, activity_type?, to_date?, minutes?, why}.
    # Kept as dicts so optional keys are omitted (not null), matching the TS contract.
    changes: list[dict[str, Any]]
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime


class GoalStats(BaseModel):
    total_minutes: int
    done_minutes: int
    items_done: int
    items_total: int
    on_track: bool
    days_left: int
    capacity_minutes: int


class GoalOut(BaseModel):
    id: str
    goal_type: GoalType
    title: str
    target_outcome: str
    deadline: date
    minutes_per_day: int
    study_days: list[int]
    current_level: str
    document_ids: list[str]
    prep_id: str | None
    status: GoalStatus
    items: list[PlanItemOut]
    pending_proposal: PlanProposalOut | None
    stats: GoalStats
    feasibility_warning: str | None
    created_at: datetime


class GoalSummary(BaseModel):
    id: str
    title: str
    goal_type: GoalType
    deadline: date
    status: str
    items_done: int
    items_total: int
    on_track: bool
    today_items: int


class TodayItem(PlanItemOut):
    goal_id: str
    goal_title: str


class TodayOut(BaseModel):
    date: Date
    items: list[TodayItem]
    total_minutes: int
