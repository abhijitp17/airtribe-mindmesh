"""Concept merging: kg_nodes.merged_into_id.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("kg_nodes") as batch:
        batch.add_column(sa.Column("merged_into_id", sa.String(32), nullable=True))
        batch.create_foreign_key("fk_kg_nodes_merged_into", "kg_nodes", ["merged_into_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_kg_nodes_merged_into_id", ["merged_into_id"])


def downgrade() -> None:
    with op.batch_alter_table("kg_nodes") as batch:
        batch.drop_index("ix_kg_nodes_merged_into_id")
        batch.drop_constraint("fk_kg_nodes_merged_into", type_="foreignkey")
        batch.drop_column("merged_into_id")
