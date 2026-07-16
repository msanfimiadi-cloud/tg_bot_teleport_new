"""add partners and referral attributions

Revision ID: 20260716_0008
Revises: 20260716_0007
Create Date: 2026-07-16 00:08:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0008"
down_revision: str | None = "20260716_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "partners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("referral_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referral_code", name="uq_partners_referral_code"),
        sa.UniqueConstraint("telegram_id", name="uq_partners_telegram_id"),
    )
    op.create_index("ix_partners_telegram_id", "partners", ["telegram_id"])
    op.create_index("ix_partners_referral_code", "partners", ["referral_code"])
    op.create_index("ix_partners_status", "partners", ["status"])
    op.create_table(
        "referral_attributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referred_user_id", sa.Integer(), nullable=False),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("referral_code_used", sa.String(length=64), nullable=False),
        sa.Column(
            "first_start_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("questionnaire_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_link_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_payment_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_payment_id", sa.Integer(), nullable=True),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("attribution_source", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["first_payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["partner_id"], ["partners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referred_user_id", name="uq_referral_attributions_referred_user_id"),
    )
    op.create_index("ix_referral_attributions_partner_id", "referral_attributions", ["partner_id"])
    op.create_index(
        "ix_referral_attributions_referred_user_id", "referral_attributions", ["referred_user_id"]
    )
    op.create_index(
        "ix_referral_attributions_first_start_at", "referral_attributions", ["first_start_at"]
    )
    op.create_index(
        "ix_referral_attributions_questionnaire_completed_at",
        "referral_attributions",
        ["questionnaire_completed_at"],
    )
    op.create_index(
        "ix_referral_attributions_first_payment_succeeded_at",
        "referral_attributions",
        ["first_payment_succeeded_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_referral_attributions_first_payment_succeeded_at", table_name="referral_attributions"
    )
    op.drop_index(
        "ix_referral_attributions_questionnaire_completed_at", table_name="referral_attributions"
    )
    op.drop_index("ix_referral_attributions_first_start_at", table_name="referral_attributions")
    op.drop_index("ix_referral_attributions_referred_user_id", table_name="referral_attributions")
    op.drop_index("ix_referral_attributions_partner_id", table_name="referral_attributions")
    op.drop_table("referral_attributions")
    op.drop_index("ix_partners_status", table_name="partners")
    op.drop_index("ix_partners_referral_code", table_name="partners")
    op.drop_index("ix_partners_telegram_id", table_name="partners")
    op.drop_table("partners")
