"""add welcome message sent timestamp

Revision ID: 20260716_0007
Revises: 20260715_0006
Create Date: 2026-07-16 00:07:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0007"
down_revision: str | None = "20260715_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("welcome_message_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "welcome_message_sent_at")
