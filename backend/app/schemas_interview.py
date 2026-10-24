"""Pydantic schemas for the interview-prep API. Shapes mirror docs/CONTRACTS.md §3 exactly."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Importance = Literal["critical", "high", "medium", "low"]
EvidenceStrength = Literal["strong", "partial", "none"]
AssessedLevel = Literal["strong", "developing", "weak", "unverified"]
Confidence = Literal["high", "medium", "low"]
GapType = Literal["strong", "knowledge_gap", "application_gap", "evidence_gap", "communication_gap", "unverified", "stretch"]
Priority = Literal["critical", "high", "medium", "low"]
CompetencyCat = Literal["technical", "domain", "tool", "behavioral", "leadership", "communication"]
QuestionCat = Literal["technical", "behavioral", "case", "resume_deep_dive", "role_specific"]
Focus = Literal["mixed", "technical", "behavioral", "resume", "case"]
Activity = Literal["learn", "practice", "story", "mock_interview", "drill"]
Dimension = Literal["role_knowledge", "applied_problem_solving", "resume_evidence", "behavioral_examples", "communication"]


# ---------- resume ----------

class ResumeBullet(BaseModel):
    # `id` may be empty on user-added bullets; the server assigns one (text is the user's own words).
    id: str = Field(default="", max_length=64)
    text: str = Field(max_length=600)


class ResumeRole(BaseModel):
    id: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=160)
    company: str = Field(default="", max_length=160)
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    bullets: list[ResumeBullet] = Field(default_factory=list, max_length=30)


class EducationItem(BaseModel):
    id: str = Field(default="", max_length=64)
    text: str = Field(max_length=300)


class ResumeParsed(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    summary: str | None = Field(default=None, max_length=1500)
    roles: list[ResumeRole] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=100)
    education: list[EducationItem] = Field(default_factory=list, max_length=20)
    certifications: list[str] = Field(default_factory=list, max_length=40)


class ResumeTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class ResumeUpdate(BaseModel):
    parsed: ResumeParsed


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_filename: str | None
    parsed: ResumeParsed
    warnings: list[str]
    user_confirmed: bool
    created_at: datetime
    updated_at: datetime


# ---------- job ----------

class Competency(BaseModel):
    id: str = Field(default="", max_length=64)
    name: str = Field(min_length=1, max_length=80)
    category: CompetencyCat = "technical"
    importance: Importance = "medium"
    required: bool = False
    evidence_quote: str = Field(default="", max_length=600)


class JobParsed(BaseModel):
    role_title: str = Field(max_length=255)
    company: str | None = Field(default=None, max_length=255)
    seniority: str | None = Field(default=None, max_length=60)
    responsibilities: list[str] = Field(default_factory=list, max_length=40)
    competencies: list[Competency] = Field(default_factory=list, max_length=40)


class JobCreate(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class JobUpdate(BaseModel):
    parsed: JobParsed


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    parsed: JobParsed
    user_confirmed: bool
    created_at: datetime
    updated_at: datetime


# ---------- prep / skill matrix ----------

class EvidenceRef(BaseModel):
    bullet_id: str
    text: str
    role_title: str


class PriorityFactors(BaseModel):
    importance: float
    gap_severity: float
    evidence_confidence: float
    urgency: float
    feasibility: float


class LinkedSource(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    page_start: int
    page_end: int
    section: str


class SkillMatchOut(BaseModel):
    id: str
    competency_id: str
    name: str
    category: CompetencyCat
    jd_importance: Importance
    resume_strength: EvidenceStrength
    resume_evidence: list[EvidenceRef]
    assessed_level: AssessedLevel
    assessed_explanation: str
    confidence: Confidence
    gap_type: GapType
    priority: Priority
    priority_factors: PriorityFactors
    recommended_action: str
    linked_sources: list[LinkedSource]
    # `{priority?, note?}`: absent keys stay absent (no nulls). Values were validated by SkillPatch.
    user_override: dict[str, str] | None


class PrepPlanItem(BaseModel):
    id: str
    competency_id: str | None
    title: str
    activity: Activity
    estimated_minutes: int
    reason: str


class ReadinessDim(BaseModel):
    dimension: Dimension
    level: AssessedLevel
    evidence_count: int
    explanation: str


class PrepCreate(BaseModel):
    resume_id: str = Field(max_length=32)
    job_id: str = Field(max_length=32)
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    interview_date: date | None = None


class PrepPatch(BaseModel):
    """Only fields present in the request body are applied; `interview_date: null` clears it."""
    interview_date: date | None = None
    document_ids: list[str] | None = Field(default=None, max_length=20)


class SkillPatch(BaseModel):
    """Only fields present are applied; `null` clears that part of the override."""
    priority: Priority | None = None
    note: str | None = Field(default=None, max_length=1000)


class PrepOut(BaseModel):
    id: str
    resume_id: str
    job_id: str
    role_title: str
    company: str | None
    interview_date: date | None
    document_ids: list[str]
    skills: list[SkillMatchOut]
    plan: list[PrepPlanItem]
    readiness: list[ReadinessDim]
    created_at: datetime
    updated_at: datetime


class PrepSummary(BaseModel):
    id: str
    role_title: str
    company: str | None
    interview_date: date | None
    critical_gaps: int
    sessions: int
    updated_at: datetime


class DeepDiveItem(BaseModel):
    bullet_id: str
    bullet: str
    questions: list[str]


# ---------- mock interview ----------

class Criterion(BaseModel):
    criterion: str
    points: int
    status: Literal["met", "partial", "missing"]
    evidence: str


class StarFlags(BaseModel):
    situation: bool
    task: bool
    action: bool
    result: bool
    reflection: bool


class Evaluation(BaseModel):
    verdict: Literal["strong", "adequate", "needs_work", "unassessed"]
    score: float
    criteria: list[Criterion]
    star: StarFlags | None
    strengths: list[str]
    improvements: list[str]
    missing_details: list[str]
    feedback: str


class InterviewTurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    position: int
    kind: Literal["question", "follow_up"]
    category: QuestionCat
    competency_id: str | None
    competency_name: str | None
    question: str
    answer: str | None
    evaluation: Evaluation | None
    asked_at: datetime
    answered_at: datetime | None


class CompetencyScore(BaseModel):
    competency_id: str
    name: str
    score: float
    attempts: int


class SessionSummary(BaseModel):
    overall: str
    by_competency: list[CompetencyScore]
    top_improvements: list[str]
    suggested_drills: list[str]


class InterviewSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    prep_id: str
    focus: Focus
    status: Literal["active", "completed"]
    target_questions: int
    turns: list[InterviewTurnOut]
    summary: SessionSummary | None
    started_at: datetime
    ended_at: datetime | None


class SessionCreate(BaseModel):
    focus: Focus = "mixed"
    target_questions: int = Field(default=5, ge=3, le=10)


class SessionListItem(BaseModel):
    id: str
    focus: str
    status: str
    questions: int
    avg_score: float | None
    started_at: datetime


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=8000)


class StudyLinkOut(BaseModel):
    concept: str
    document_id: str
    document_title: str
    page: int
    verified: bool  # linked by a rule (same words) rather than a model's judgement


class ShareOut(BaseModel):
    id: str
    url: str | None = None  # only when just created: the token isn't stored
    expires_at: datetime
    views: int = 0
    created_at: datetime
