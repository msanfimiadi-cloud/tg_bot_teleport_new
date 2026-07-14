"""admin subscriptions and logs

Revision ID: 20260714_0002
Revises: 20260714_0001
Create Date: 2026-07-14 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0002"
down_revision: str | None = "20260714_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questionnaires", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payment_provider", sa.String(length=64), nullable=True),
        sa.Column("last_payment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.BigInteger(), nullable=True),
        sa.Column("activation_source", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_subscriptions_user_id"),
    )
    op.create_table(
        "admin_action_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_action_logs_admin_id"), "admin_action_logs", ["admin_id"], unique=False
    )
    op.create_index(
        op.f("ix_admin_action_logs_action"), "admin_action_logs", ["action"], unique=False
    )
    op.create_index(
        op.f("ix_admin_action_logs_target_user_id"),
        "admin_action_logs",
        ["target_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_action_logs_target_user_id"), table_name="admin_action_logs")
    op.drop_index(op.f("ix_admin_action_logs_action"), table_name="admin_action_logs")
    op.drop_index(op.f("ix_admin_action_logs_admin_id"), table_name="admin_action_logs")
    op.drop_table("admin_action_logs")
    op.drop_table("subscriptions")
    op.drop_column("questionnaires", "reviewed_at")
