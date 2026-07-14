"""audit race condition indexes

Revision ID: 20260714_0005
Revises: 20260714_0004
Create Date: 2026-07-14 00:05:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260714_0005"
down_revision: str | None = "20260714_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_payments_user_created", "payments", ["user_id", "created_at"])
    op.create_index("ix_subscriptions_status_expires", "subscriptions", ["status", "expires_at"])
    op.create_index(
        "ix_questionnaires_review_queue",
        "questionnaires",
        ["status", "reviewed_at", "completed_at"],
    )
    op.create_index("ix_event_logs_user_created", "event_logs", ["user_id", "created_at"])
    op.create_index(
        "ix_admin_action_logs_target_created", "admin_action_logs", ["target_user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_admin_action_logs_target_created", table_name="admin_action_logs")
    op.drop_index("ix_event_logs_user_created", table_name="event_logs")
    op.drop_index("ix_questionnaires_review_queue", table_name="questionnaires")
    op.drop_index("ix_subscriptions_status_expires", table_name="subscriptions")
    op.drop_index("ix_payments_user_created", table_name="payments")
