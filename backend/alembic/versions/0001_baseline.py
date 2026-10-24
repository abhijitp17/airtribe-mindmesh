"""Baseline: every table as of slice 2 (models.py, models_interview.py, models_goals.py, models_jobs.py).

Hand-written to mirror the SQLAlchemy models exactly, including index names
(SQLAlchemy's `index=True` convention is ix_<table>_<column>) so that
`alembic revision --autogenerate` against this baseline produces no diff.

Revision ID: 0001
Revises:
Create Date: 2026-10-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def _id() -> sa.Column:
    return sa.Column("id", sa.String(32), primary_key=True)


def _owner() -> sa.Column:
    return sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


def _ix(table: str, *cols: str, name: str | None = None, unique: bool = False) -> None:
    op.create_index(name or f"ix_{table}_{cols[0]}", table, list(cols), unique=unique)


def upgrade() -> None:
    # ---------------------------------------------------------------- models.py
    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    _ix("users", "email", unique=True)

    op.create_table(
        "documents",
        _id(),
        _owner(),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("low_text_pages", sa.JSON(), nullable=False),
        sa.Column("processing_version", sa.String(20), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
    )
    _ix("documents", "owner_id")

    op.create_table(
        "chunks",
        _id(),
        sa.Column("document_id", sa.String(32), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        _owner(),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    _ix("chunks", "document_id")
    _ix("chunks", "owner_id")
    _ix("chunks", "document_id", "ordinal", name="ix_chunks_doc_ordinal")

    op.create_table(
        "chat_messages",
        _id(),
        _owner(),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    _ix("chat_messages", "owner_id")
    _ix("chat_messages", "created_at")

    op.create_table(
        "quizzes",
        _id(),
        _owner(),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("focus", sa.String(255), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
    )
    _ix("quizzes", "owner_id")

    op.create_table(
        "questions",
        _id(),
        sa.Column("quiz_id", sa.String(32), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
        _owner(),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("qtype", sa.String(10), nullable=False),
        sa.Column("concept", sa.String(120), nullable=False),
        sa.Column("difficulty", sa.String(10), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("correct_index", sa.Integer(), nullable=True),
        sa.Column("answer_key", sa.Text(), nullable=False),
        sa.Column("rubric", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("source_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("flagged", sa.Text(), nullable=True),
        sa.Column("generator_version", sa.String(40), nullable=False),
    )
    _ix("questions", "quiz_id")
    _ix("questions", "owner_id")
    _ix("questions", "concept")

    op.create_table(
        "attempts",
        _id(),
        _owner(),
        sa.Column("question_id", sa.String(32), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("selected_index", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(12), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("evaluator_version", sa.String(80), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    _ix("attempts", "owner_id")
    _ix("attempts", "question_id")
    _ix("attempts", "created_at")

    op.create_table(
        "usage_events",
        _id(),
        _owner(),
        sa.Column("task", sa.String(40), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    _ix("usage_events", "owner_id")
    _ix("usage_events", "created_at")

    # ---------------------------------------------------------------- models_interview.py
    op.create_table(
        "resume_profiles",
        _id(),
        _owner(),
        sa.Column("source_filename", sa.String(255), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("parsed", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("user_confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
    )
    _ix("resume_profiles", "owner_id")

    op.create_table(
        "job_profiles",
        _id(),
        _owner(),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("role_title", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("seniority", sa.String(60), nullable=True),
        sa.Column("parsed", sa.JSON(), nullable=False),
        sa.Column("user_confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
    )
    _ix("job_profiles", "owner_id")

    op.create_table(
        "role_preps",
        _id(),
        _owner(),
        sa.Column("resume_id", sa.String(32), sa.ForeignKey("resume_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("job_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("interview_date", sa.Date(), nullable=True),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
    )
    _ix("role_preps", "owner_id")

    op.create_table(
        "skill_matches",
        _id(),
        sa.Column("prep_id", sa.String(32), sa.ForeignKey("role_preps.id", ondelete="CASCADE"), nullable=False),
        _owner(),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("jd_importance", sa.String(10), nullable=False),
        sa.Column("resume_strength", sa.String(10), nullable=False),
        sa.Column("resume_evidence", sa.JSON(), nullable=False),
        sa.Column("assessed_level", sa.String(12), nullable=False),
        sa.Column("assessed_explanation", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("gap_type", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("priority_factors", sa.JSON(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("linked_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("user_override", sa.JSON(), nullable=True),
    )
    _ix("skill_matches", "prep_id")
    _ix("skill_matches", "owner_id")

    op.create_table(
        "interview_sessions",
        _id(),
        sa.Column("prep_id", sa.String(32), sa.ForeignKey("role_preps.id", ondelete="CASCADE"), nullable=False),
        _owner(),
        sa.Column("focus", sa.String(20), nullable=False),
        sa.Column("target_questions", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("rubric_version", sa.String(80), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("ended_at", TZ, nullable=True),
    )
    _ix("interview_sessions", "prep_id")
    _ix("interview_sessions", "owner_id")

    op.create_table(
        "interview_turns",
        _id(),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False),
        _owner(),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("competency_id", sa.String(64), nullable=True),
        sa.Column("competency_name", sa.String(160), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("evaluation", sa.JSON(), nullable=True),
        sa.Column("asked_at", TZ, nullable=False),
        sa.Column("answered_at", TZ, nullable=True),
    )
    _ix("interview_turns", "session_id")
    _ix("interview_turns", "owner_id")

    # ---------------------------------------------------------------- models_goals.py
    op.create_table(
        "goals",
        _id(),
        _owner(),
        sa.Column("goal_type", sa.String(12), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("target_outcome", sa.Text(), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=False),
        sa.Column("minutes_per_day", sa.Integer(), nullable=False),
        sa.Column("study_days", sa.JSON(), nullable=False),
        sa.Column("current_level", sa.String(20), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("prep_id", sa.String(32), sa.ForeignKey("role_preps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
    )
    _ix("goals", "owner_id")

    op.create_table(
        "plan_items",
        _id(),
        sa.Column("goal_id", sa.String(32), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
        _owner(),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("concept", sa.String(120), nullable=True),
        sa.Column("activity_type", sa.String(16), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("source_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("user_edited", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("completed_at", TZ, nullable=True),
    )
    _ix("plan_items", "goal_id")
    _ix("plan_items", "owner_id")
    _ix("plan_items", "scheduled_date")

    op.create_table(
        "plan_proposals",
        _id(),
        sa.Column("goal_id", sa.String(32), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
        _owner(),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    _ix("plan_proposals", "goal_id")
    _ix("plan_proposals", "owner_id")

    # ---------------------------------------------------------------- models_jobs.py (app/jobs.py)
    op.create_table(
        "jobs",
        _id(),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", TZ, nullable=False),
        sa.Column("locked_at", TZ, nullable=True),
        sa.Column("locked_by", sa.String(128), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
    )
    _ix("jobs", "status", "run_after", name="ix_jobs_status_run_after")


# Reverse FK order.
_TABLES = [
    "jobs",
    "plan_proposals", "plan_items", "goals",
    "interview_turns", "interview_sessions", "skill_matches", "role_preps", "job_profiles", "resume_profiles",
    "usage_events", "attempts", "questions", "quizzes", "chat_messages", "chunks", "documents", "users",
]


def downgrade() -> None:
    for t in _TABLES:
        op.drop_table(t)  # indexes are dropped with their table
