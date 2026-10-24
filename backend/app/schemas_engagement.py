"""Schemas for Today, timed sessions, weekly target, onboarding, debriefs and the public report.

Shapes mirror web/src/lib/api-engagement.ts exactly (CONTRACTS §7).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from .schemas_interview import AssessedLevel, GapType, Importance, Priority

PreparingFor = Literal["interview", "exam", "learn"]
Minutes = Literal[5, 15, 30]
StepKind = Literal["review", "quiz", "learn", "story", "mock_question", "plan_item"]
StepStatus = Literal["pending", "done", "skipped"]
WinKind = Literal["level_up", "gap_closed", "first_answer", "target_met"]
SessionStatus = Literal["active", "completed", "abandoned"]
DebriefOutcome = Literal["offer", "next_round", "rejected", "not_happened", "prefer_not"]
DebriefNext = Literal["next_round", "new_role", "learning_goal", "none"]

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


# ---------- prefs ----------

class Prefs(BaseModel):
    preparing_for: PreparingFor | None
    weekly_target: int
    default_minutes: Minutes
    reminders: bool
    quiet_start: str
    quiet_end: str
    reduce_transparency: bool
    onboarded: bool


class PrefsPatch(BaseModel):
    """Partial Prefs. `null` on a non-nullable field means "unchanged"; `onboarded: true` sets onboarded_at."""
    preparing_for: PreparingFor | None = None
    weekly_target: int | None = Field(default=None, ge=1, le=7)
    default_minutes: Minutes | None = None
    reminders: bool | None = None
    quiet_start: str | None = Field(default=None, pattern=HHMM)
    quiet_end: str | None = Field(default=None, pattern=HHMM)
    reduce_transparency: bool | None = None
    onboarded: Literal[True] | None = None


# ---------- steps ----------

class QuizTarget(BaseModel):
    type: Literal["quiz"]
    quiz_id: str | None
    document_ids: list[str]
    focus: str | None


class InterviewTarget(BaseModel):
    type: Literal["interview"]
    prep_id: str
    session_id: str | None


class PlanItemTarget(BaseModel):
    type: Literal["plan_item"]
    goal_id: str
    item_id: str


class LinkTarget(BaseModel):
    type: Literal["link"]
    href: str


StepTarget = Annotated[Union[QuizTarget, InterviewTarget, PlanItemTarget, LinkTarget], Field(discriminator="type")]


class SessionStep(BaseModel):
    id: str
    kind: StepKind
    title: str
    detail: str
    minutes: int
    concept: str | None
    target: StepTarget
    status: StepStatus


class Win(BaseModel):
    kind: WinKind
    title: str
    detail: str


# ---------- week / today ----------

class WeekDay(BaseModel):
    date: str  # YYYY-MM-DD
    practised: bool
    is_today: bool


class WeekOut(BaseModel):
    target: int
    done: int
    days: list[WeekDay]


class Countdown(BaseModel):
    prep_id: str
    role_title: str
    company: str | None
    interview_date: date
    days_left: int


class DebriefDue(BaseModel):
    prep_id: str
    role_title: str
    company: str | None
    interview_date: date


class TodayPreview(BaseModel):
    greeting_name: str
    countdown: Countdown | None
    week: WeekOut
    suggestions: dict[Literal["5", "15", "30"], list[SessionStep]]
    last_win: Win | None
    debrief_due: DebriefDue | None
    empty_reason: Literal["no_material", "no_goal"] | None
    library_count: int


# ---------- sessions ----------

class SessionCreate(BaseModel):
    minutes: Minutes


class StepPatch(BaseModel):
    status: Literal["done", "skipped"]
    quiz_id: str | None = Field(default=None, max_length=64)


class StudySessionOut(BaseModel):
    id: str
    minutes: Minutes
    steps: list[SessionStep]
    status: SessionStatus
    wins: list[Win]
    started_at: datetime
    completed_at: datetime | None


# ---------- debrief ----------

class DebriefIn(BaseModel):
    outcome: DebriefOutcome
    next_step: DebriefNext | None = None
    note: str = Field(default="", max_length=2000)


class FollowUp(BaseModel):
    type: Literal["goal", "prep"]
    id: str


class DebriefOut(BaseModel):
    id: str
    prep_id: str
    outcome: DebriefOutcome
    note: str
    next_step: DebriefNext | None
    created_at: datetime
    follow_up: FollowUp | None


# ---------- public gap report ----------

class GapReportIn(BaseModel):
    resume_text: str = Field(min_length=200, max_length=20000)
    job_text: str = Field(min_length=200, max_length=20000)


class JobUrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class JobUrlOut(BaseModel):
    text: str
    title: str | None = None
    company: str | None = None


class ClaimIn(BaseModel):
    report_token: str = Field(min_length=1, max_length=64)


class ClaimOut(BaseModel):
    prep_id: str


class PublicSkill(BaseModel):
    name: str
    importance: Importance
    gap_type: GapType
    priority: Priority
    assessed_level: AssessedLevel
    evidence_quote: str | None
    jd_quote: str
    why: str
    next_step: str


class PublicReport(BaseModel):
    token: str
    role_title: str
    company: str | None
    skills: list[PublicSkill]
    hidden_count: int
    warnings: list[str]
    expires_at: datetime


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    props: dict = Field(default_factory=dict, max_length=8)


class ExperimentsOut(BaseModel):
    onboarding: str  # goal_first | upload_first
