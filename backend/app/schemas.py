from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Level = Literal["beginner", "standard", "advanced"]
# Simple check; avoids the email-validator dependency. Real verification = confirmation email (later).
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SignupIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=120)
    # Optional: a signed-out gap report to save to the new account (routers/public.py).
    report_token: str | None = Field(default=None, max_length=64)


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    display_name: str
    level: str


class TokenOut(BaseModel):
    token: str
    user: UserOut


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    title: str | None
    status: str
    status_detail: str | None
    page_count: int | None
    low_text_pages: list[int]
    size_bytes: int
    created_at: datetime
    pages_done: int | None = None  # while processing: pages read so far (the first pages can already be used)
    processing_started_at: datetime | None = None


class ConceptOut(BaseModel):
    name: str
    page: int
    quote: str
    chunk_id: str


class DocumentRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ordinal: int
    page_start: int
    page_end: int
    section: str
    text: str


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    document_ids: list[str] = Field(min_length=1, max_length=20)
    level: Level = "standard"
    allow_general: bool = False


class CitationOut(BaseModel):
    label: str
    chunk_id: str
    document_id: str
    document_title: str
    quote: str
    page_start: int
    page_end: int
    section: str


class AskOut(BaseModel):
    answer: str
    status: str
    citations: list[CitationOut]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    role: str
    content: str
    status: str | None
    citations: list[dict]
    created_at: datetime


class QuizCreate(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=20)
    count: int = Field(default=5, ge=1, le=15)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    focus: str | None = Field(default=None, max_length=255)


class QuestionOut(BaseModel):
    """Question as shown to the learner. Answer key is hidden until attempted."""
    id: str
    position: int
    qtype: str
    concept: str
    difficulty: str
    prompt: str
    options: list[str]
    sources: list[dict]
    flagged: bool
    last_attempt: AttemptOut | None = None


class QuizOut(BaseModel):
    id: str
    title: str
    focus: str | None
    document_ids: list[str]
    created_at: datetime
    questions: list[QuestionOut]


class QuizSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    question_count: int
    answered: int
    avg_score: float | None


class AttemptIn(BaseModel):
    answer_text: str | None = Field(default=None, max_length=6000)
    selected_index: int | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)


class AttemptOut(BaseModel):
    id: str
    verdict: str
    score: float
    feedback: str
    missing: list[str]
    criteria: list[dict]
    answer_key: str
    explanation: str
    correct_index: int | None
    selected_index: int | None
    response_text: str | None
    created_at: datetime


FLAG_REASONS = ("wrong_answer", "unclear", "not_in_document", "other")


class FlagIn(BaseModel):
    # One of FLAG_REASONS. Older clients sent free text here; that is stored as "other" + note.
    reason: str = Field(min_length=3, max_length=1000)
    note: str = Field(default="", max_length=1000)


class FlaggedQuestionOut(BaseModel):
    id: str
    quiz_id: str
    quiz_title: str
    prompt: str
    concept: str
    reason: str
    note: str
    flagged_at: datetime | None


class MasteryOut(BaseModel):
    concept: str
    estimate: float
    level: str
    evidence_count: int
    last_assessed_at: datetime | None
    due_for_review: bool
    explanation: str


class ProgressOut(BaseModel):
    concepts: list[MasteryOut]
    totals: dict
    next_action: dict


QuestionOut.model_rebuild()
