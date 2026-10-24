"""Slice 3 engagement tables (models_engagement.py): user_prefs, study_sessions, interview_debriefs.

Hand-written to mirror the SQLAlchemy models exactly, including index names
(ix_<table>_<column>), so autogenerate against head produces no diff.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def _owner(primary_key: bool = False) -> sa.Column:
    return sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"),
                     primary_key=primary_key, nullable=False)


def upgrade() -> None:
    op.create_table(
        "user_prefs",
        _owner(primary_key=True),
        sa.Column("preparing_for", sa.String(12), nullable=True),
        sa.Column("weekly_target", sa.Integer(), nullable=False),
        sa.Column("default_minutes", sa.Integer(), nullable=False),
        sa.Column("reminders", sa.Boolean(), nullable=False),
        sa.Column("quiet_start", sa.String(5), nullable=False),
        sa.Column("quiet_end", sa.String(5), nullable=False),
        sa.Column("reduce_transparency", sa.Boolean(), nullable=False),
        sa.Column("onboarded_at", TZ, nullable=True),
        sa.Column("updated_at", TZ, nullable=False),
    )

    op.create_table(
        "study_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        _owner(),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("wins", sa.JSON(), nullable=False),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("completed_at", TZ, nullable=True),
    )
    op.create_index("ix_study_sessions_owner_id", "study_sessions", ["owner_id"])
    op.create_index("ix_study_sessions_started_at", "study_sessions", ["started_at"])

    op.create_table(
        "interview_debriefs",
        sa.Column("id", sa.String(32), primary_key=True),
        _owner(),
        sa.Column("prep_id", sa.String(32), sa.ForeignKey("role_preps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("next_step", sa.String(16), nullable=True),
        sa.Column("interview_date", sa.Date(), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_interview_debriefs_owner_id", "interview_debriefs", ["owner_id"])
    op.create_index("ix_interview_debriefs_prep_id", "interview_debriefs", ["prep_id"])


def downgrade() -> None:
    for t in ("interview_debriefs", "study_sessions", "user_prefs"):
        op.drop_table(t)  # indexes are dropped with their table
