"""Product analytics events (activation metric, onboarding experiment).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("props", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_events_owner_id", "product_events", ["owner_id"])
    op.create_index("ix_product_events_created_at", "product_events", ["created_at"])
    op.create_index("ix_product_events_owner_name", "product_events", ["owner_id", "name"])


def downgrade() -> None:
    op.drop_table("product_events")
