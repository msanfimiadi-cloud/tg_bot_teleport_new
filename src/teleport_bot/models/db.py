from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from teleport_bot.db.base import Base, TimestampMixin
from teleport_bot.models.enums import (
    FunnelStatus,
    OnboardingStatus,
    QuestionnaireStatus,
    SubscriptionStatus,
)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), default="")
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    onboarding_status: Mapped[str] = mapped_column(String(64), default=OnboardingStatus.NEW.value)
    funnel_status: Mapped[str] = mapped_column(String(64), default=FunnelStatus.ONBOARDING.value)
    first_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    questionnaire: Mapped["Questionnaire"] = relationship(back_populates="user", uselist=False)
    subscription: Mapped["Subscription | None"] = relationship(back_populates="user", uselist=False)
    payments: Mapped[list["Payment"]] = relationship(back_populates="user")


class Questionnaire(TimestampMixin, Base):
    __tablename__ = "questionnaires"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_questionnaires_user_id"),
        Index("ix_questionnaires_review_queue", "status", "reviewed_at", "completed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    name_and_age: Mapped[str | None] = mapped_column(String(200), nullable=True)
    what_annoys: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_is_important: Mapped[str | None] = mapped_column(Text, nullable=True)
    self_definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    intention: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=QuestionnaireStatus.NOT_STARTED.value)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="questionnaire")


class Subscription(TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_subscriptions_user_id"),
        Index("ix_subscriptions_status_expires", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(32), default=SubscriptionStatus.INACTIVE.value)
    payment_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    activation_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="subscription")
    last_payment: Mapped["Payment | None"] = relationship(foreign_keys=[last_payment_id])


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_payment_id", name="uq_payments_provider_payment_id"),
        UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        Index("ix_payments_user_id", "user_id"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_created_at", "created_at"),
        Index("ix_payments_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32), default="yookassa")
    provider_payment_id: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Any] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    confirmation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    save_payment_method_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_method_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_payment_method_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    applied_to_subscription_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="payments")


class PaymentMethod(TimestampMixin, Base):
    __tablename__ = "payment_methods"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_payment_method_id", name="uq_payment_methods_provider_method_id"
        ),
        Index("ix_payment_methods_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32), default="yookassa")
    provider_payment_method_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    reusable: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SubscriptionReminder(Base):
    __tablename__ = "subscription_reminders"
    __table_args__ = (
        UniqueConstraint("subscription_id", "reminder_type", name="uq_subscription_reminder_type"),
        Index("ix_subscription_reminders_subscription_id", "subscription_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    reminder_type: Mapped[str] = mapped_column(String(32))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"
    __table_args__ = (Index("ix_admin_action_logs_target_created", "target_user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    target_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventLog(Base):
    __tablename__ = "event_logs"
    __table_args__ = (Index("ix_event_logs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
