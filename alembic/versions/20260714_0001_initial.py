"""initial schema

Revision ID: 20260714_0001
Revises:
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("onboarding_status", sa.String(length=64), nullable=False),
        sa.Column("funnel_status", sa.String(length=64), nullable=False),
        sa.Column(
            "first_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)
    op.create_table(
        "questionnaires",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name_and_age", sa.String(length=200), nullable=True),
        sa.Column("what_annoys", sa.Text(), nullable=True),
        sa.Column("what_is_important", sa.Text(), nullable=True),
        sa.Column("self_definition", sa.Text(), nullable=True),
        sa.Column("intention", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_questionnaires_user_id"),
    )
    op.create_table(
        "event_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_event_logs_event_type"), "event_logs", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_event_logs_event_type"), table_name="event_logs")
    op.drop_table("event_logs")
    op.drop_table("questionnaires")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
