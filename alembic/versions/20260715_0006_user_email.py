"""add nullable user email

Revision ID: 20260715_0006
Revises: 20260714_0005
Create Date: 2026-07-15 00:06:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260715_0006"
down_revision: str | None = "20260714_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "email")
