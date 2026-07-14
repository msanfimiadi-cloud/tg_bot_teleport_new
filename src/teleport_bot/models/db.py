from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from teleport_bot.db.base import Base, TimestampMixin
from teleport_bot.models.enums import FunnelStatus, OnboardingStatus, QuestionnaireStatus


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


class Questionnaire(TimestampMixin, Base):
    __tablename__ = "questionnaires"
    __table_args__ = (UniqueConstraint("user_id", name="uq_questionnaires_user_id"),)

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

    user: Mapped[User] = relationship(back_populates="questionnaire")


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
