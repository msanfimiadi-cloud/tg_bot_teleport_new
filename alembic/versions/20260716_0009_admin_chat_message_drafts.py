"""admin chat message drafts

Revision ID: 20260716_0009
Revises: 20260716_0008
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0009"
down_revision: str | None = "20260716_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_chat_message_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_admin_chat_message_drafts_admin_telegram_id",
        "admin_chat_message_drafts",
        ["admin_telegram_id"],
    )
    op.create_index(
        "ix_admin_chat_message_drafts_text_hash", "admin_chat_message_drafts", ["text_hash"]
    )
    op.create_index("ix_admin_chat_message_drafts_status", "admin_chat_message_drafts", ["status"])
    op.create_index(
        "ix_admin_chat_message_drafts_admin_status",
        "admin_chat_message_drafts",
        ["admin_telegram_id", "status"],
    )
    op.create_index(
        "ix_admin_chat_message_drafts_status_updated",
        "admin_chat_message_drafts",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_chat_message_drafts_status_updated", table_name="admin_chat_message_drafts"
    )
    op.drop_index(
        "ix_admin_chat_message_drafts_admin_status", table_name="admin_chat_message_drafts"
    )
    op.drop_index("ix_admin_chat_message_drafts_status", table_name="admin_chat_message_drafts")
    op.drop_index("ix_admin_chat_message_drafts_text_hash", table_name="admin_chat_message_drafts")
    op.drop_index(
        "ix_admin_chat_message_drafts_admin_telegram_id", table_name="admin_chat_message_drafts"
    )
    op.drop_table("admin_chat_message_drafts")
