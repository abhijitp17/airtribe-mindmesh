"""Dense embeddings per chunk and model (portable float32 bytes; pgvector column added by a tool).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("chunk_id", sa.String(32), sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(32), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chunk_id", "model", name="uq_chunk_embeddings_chunk_model"),
    )
    op.create_index("ix_chunk_embeddings_chunk_id", "chunk_embeddings", ["chunk_id"])
    op.create_index("ix_chunk_embeddings_owner_id", "chunk_embeddings", ["owner_id"])
    op.create_index("ix_chunk_embeddings_document_id", "chunk_embeddings", ["document_id"])


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
