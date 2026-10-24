"""Link users to an identity provider (Clerk): users.auth_provider, users.external_id.

password_hash becomes nullable (Clerk users have none). Existing rows are local
accounts. Batch mode keeps the ALTERs working on SQLite.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("auth_provider", sa.String(16), nullable=False, server_default="local"))
        batch.add_column(sa.Column("external_id", sa.String(64), nullable=True))
        batch.alter_column("password_hash", existing_type=sa.String(255), nullable=True)
        batch.create_index("ix_users_external_id", ["external_id"], unique=True)
    # The default only backfills existing rows; the model sets it for new ones.
    with op.batch_alter_table("users") as batch:
        batch.alter_column("auth_provider", existing_type=sa.String(16), server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_external_id")
        batch.drop_column("external_id")
        batch.drop_column("auth_provider")
        batch.alter_column("password_hash", existing_type=sa.String(255), nullable=False)
