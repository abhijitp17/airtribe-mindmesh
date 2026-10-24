"""Email reminders: user_prefs.timezone and email_log (one email per kind per user-local day).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_prefs") as batch:
        batch.add_column(sa.Column("timezone", sa.String(64), nullable=True))
    op.create_table(
        "email_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "kind", "local_date", name="uq_email_log_owner_kind_date"),
    )
    op.create_index("ix_email_log_owner_id", "email_log", ["owner_id"])


def downgrade() -> None:
    op.drop_table("email_log")
    with op.batch_alter_table("user_prefs") as batch:
        batch.drop_column("timezone")
