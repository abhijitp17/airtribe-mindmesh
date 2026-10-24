"""Structured question reports: questions.flag_reason, questions.flagged_at.

`flagged` stays the marker (non-null = reported, now holding the optional note), so the
mastery queries that skip reported questions are unchanged. Existing reports become "other".

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.add_column(sa.Column("flag_reason", sa.String(24), nullable=True))
        batch.add_column(sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE questions SET flag_reason = 'other' WHERE flagged IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("flagged_at")
        batch.drop_column("flag_reason")
