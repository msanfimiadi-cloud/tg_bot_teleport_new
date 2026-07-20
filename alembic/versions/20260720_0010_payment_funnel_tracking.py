"""payment funnel tracking

Revision ID: 20260720_0010
Revises: 20260716_0009
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0010"
down_revision: str | None = "20260716_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("payment_email_requested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("email_saved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "payments", sa.Column("confirmation_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "payments", sa.Column("confirmation_opened_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "payments", sa.Column("success_notified_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("payments", "success_notified_at")
    op.drop_column("payments", "confirmation_opened_at")
    op.drop_column("payments", "confirmation_sent_at")
    op.drop_column("users", "email_saved_at")
    op.drop_column("users", "payment_email_requested_at")
