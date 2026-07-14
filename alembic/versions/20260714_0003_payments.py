"""yookassa payments

Revision ID: 20260714_0003
Revises: 20260714_0002
Create Date: 2026-07-14 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0003"
down_revision: str | None = "20260714_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("confirmation_url", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_recurring", sa.Boolean(), nullable=False),
        sa.Column("save_payment_method_requested", sa.Boolean(), nullable=False),
        sa.Column("payment_method_saved", sa.Boolean(), nullable=False),
        sa.Column("provider_payment_method_id", sa.String(length=128), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("applied_to_subscription_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_payment_id", name="uq_payments_provider_payment_id"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"], unique=False)
    op.create_index("ix_payments_status", "payments", ["status"], unique=False)
    op.create_index("ix_payments_created_at", "payments", ["created_at"], unique=False)
    op.create_table(
        "payment_methods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_payment_method_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reusable", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "first_saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_payment_method_id", name="uq_payment_methods_provider_method_id"
        ),
    )
    op.create_index("ix_payment_methods_user_id", "payment_methods", ["user_id"], unique=False)
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.add_column(sa.Column("last_payment_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_subscriptions_last_payment_id",
            "payments",
            ["last_payment_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.drop_constraint("fk_subscriptions_last_payment_id", type_="foreignkey")
        batch_op.drop_column("last_payment_id")
    op.drop_index("ix_payment_methods_user_id", table_name="payment_methods")
    op.drop_table("payment_methods")
    op.drop_index("ix_payments_created_at", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")
