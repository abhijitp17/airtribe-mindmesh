"""Processing progress: documents.pages_done and documents.processing_started_at.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("pages_done", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("processing_started_at")
        batch.drop_column("pages_done")
