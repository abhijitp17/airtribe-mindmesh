"""P1 knowledge graph foundation (models_kg.py): kg_nodes, kg_edges.

Hand-written to mirror the SQLAlchemy models exactly, so `alembic check` finds no
diff. Both tables have owner_id, so re-running sql/rls.sql puts them under RLS.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def _owner() -> sa.Column:
    return sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "kg_nodes",
        sa.Column("id", sa.String(32), primary_key=True),
        _owner(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("canonical_key", sa.String(120), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.UniqueConstraint("owner_id", "kind", "canonical_key", name="uq_kg_nodes_owner_kind_key"),
    )
    op.create_index("ix_kg_nodes_owner_id", "kg_nodes", ["owner_id"])

    op.create_table(
        "kg_edges",
        sa.Column("id", sa.String(32), primary_key=True),
        _owner(),
        sa.Column("src_id", sa.String(32), sa.ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dst_id", sa.String(32), sa.ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rel", sa.String(24), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.UniqueConstraint("owner_id", "src_id", "dst_id", "rel", name="uq_kg_edges_owner_src_dst_rel"),
        sa.CheckConstraint("src_id <> dst_id", name="ck_kg_edges_no_self_loop"),
    )
    op.create_index("ix_kg_edges_owner_id", "kg_edges", ["owner_id"])
    op.create_index("ix_kg_edges_owner_dst_rel", "kg_edges", ["owner_id", "dst_id", "rel"])
    op.create_index("ix_kg_edges_owner_src_rel", "kg_edges", ["owner_id", "src_id", "rel"])


def downgrade() -> None:
    op.drop_table("kg_edges")
    op.drop_table("kg_nodes")
