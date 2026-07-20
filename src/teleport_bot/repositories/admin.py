from datetime import UTC, date, datetime, time, timedelta
from typing import Any, TypedDict

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from teleport_bot.models.db import (
    AdminActionLog,
    EventLog,
    Payment,
    Questionnaire,
    Subscription,
    User,
)
from teleport_bot.models.enums import AdminAction, QuestionnaireStatus, SubscriptionStatus
from teleport_bot.repositories.events import safe_log_payload


class AdminLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        admin_id: int,
        action: AdminAction,
        target_user_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AdminActionLog:
        row = AdminActionLog(
            admin_id=admin_id,
            action=action.value,
            target_user_id=target_user_id,
            payload=safe_log_payload(payload),
        )
        self.session.add(row)
        await self.session.flush()
        return row


class UserHistory(TypedDict):
    user: User
    questionnaire: Questionnaire
    subscription: Subscription | None
    payments: list[Payment]
    events: list[EventLog]
    admin_logs: list[AdminActionLog]


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def new_questionnaires(self) -> list[Questionnaire]:
        result = await self.session.scalars(
            select(Questionnaire)
            .where(
                Questionnaire.status == QuestionnaireStatus.COMPLETED.value,
                Questionnaire.reviewed_at.is_(None),
            )
            .options(selectinload(Questionnaire.user))
            .order_by(Questionnaire.completed_at.asc())
        )
        return list(result.all())

    async def mark_questionnaire_viewed(self, questionnaire: Questionnaire) -> None:
        questionnaire.reviewed_at = datetime.now(UTC)
        await self.session.flush()

    async def users(self, query: str | None = None, page: int = 1, per_page: int = 5) -> list[User]:
        stmt = select(User).options(
            selectinload(User.questionnaire), selectinload(User.subscription)
        )
        if query:
            like = f"%{query.lower()}%"
            conditions: list[ColumnElement[bool]] = [
                func.lower(User.username).like(like),
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
            ]
            if query.isdigit():
                conditions.append(User.telegram_id == int(query))
            stmt = stmt.where(or_(*conditions))
        stmt = (
            stmt.order_by(User.created_at.desc())
            .offset(max(page - 1, 0) * per_page)
            .limit(per_page)
        )
        return list((await self.session.scalars(stmt)).all())

    async def users_count(self, query: str | None = None) -> int:
        stmt = select(func.count(User.id))
        if query:
            like = f"%{query.lower()}%"
            conditions: list[ColumnElement[bool]] = [
                func.lower(User.username).like(like),
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
            ]
            if query.isdigit():
                conditions.append(User.telegram_id == int(query))
            stmt = stmt.where(or_(*conditions))
        return int(await self.session.scalar(stmt) or 0)

    async def stats(self) -> dict[str, int]:
        now = datetime.now(UTC)
        today_start = datetime.combine(date.today(), time.min, tzinfo=UTC)
        week_start = now - timedelta(days=7)
        total_users = await self.session.scalar(select(func.count(User.id)))
        today_users = await self.session.scalar(
            select(func.count(User.id)).where(User.created_at >= today_start)
        )
        week_users = await self.session.scalar(
            select(func.count(User.id)).where(User.created_at >= week_start)
        )
        completed = await self.session.scalar(
            select(func.count(Questionnaire.id)).where(
                Questionnaire.status == QuestionnaireStatus.COMPLETED.value
            )
        )
        active = await self.session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.status.in_(
                    [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.MANUAL.value]
                )
            )
        )
        inactive = await self.session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.status == SubscriptionStatus.INACTIVE.value
            )
        )
        return {
            "total_users": total_users or 0,
            "new_today": today_users or 0,
            "new_week": week_users or 0,
            "completed_questionnaires": completed or 0,
            "active_subscriptions": active or 0,
            "inactive_subscriptions": inactive or 0,
        }

    async def subscriptions(self, filter_name: str = "active") -> list[Subscription]:
        now = datetime.now(UTC)
        stmt = (
            select(Subscription)
            .options(selectinload(Subscription.user))
            .order_by(Subscription.expires_at.asc())
        )
        if filter_name == "expired":
            stmt = stmt.where(Subscription.status == SubscriptionStatus.EXPIRED.value)
        elif filter_name == "ending_7_days":
            stmt = stmt.where(
                Subscription.status.in_(
                    [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.MANUAL.value]
                ),
                Subscription.expires_at <= now + timedelta(days=7),
                Subscription.expires_at >= now,
            )
        elif filter_name == "manual":
            stmt = stmt.where(Subscription.activation_source == "manual")
        elif filter_name == "migrated":
            stmt = stmt.where(Subscription.activation_source == "migration")
        else:
            stmt = stmt.where(
                Subscription.status.in_(
                    [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.MANUAL.value]
                )
            )
        return list((await self.session.scalars(stmt.limit(20))).all())

    async def user_history(self, telegram_id: int) -> UserHistory | None:
        user = await self.session.scalar(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(
                selectinload(User.questionnaire),
                selectinload(User.subscription),
                selectinload(User.payments),
            )
        )
        if user is None:
            return None
        events = list(
            (
                await self.session.scalars(
                    select(EventLog)
                    .where(EventLog.user_id == user.id)
                    .order_by(EventLog.created_at.asc())
                )
            ).all()
        )
        admin_logs = list(
            (
                await self.session.scalars(
                    select(AdminActionLog)
                    .where(AdminActionLog.target_user_id == telegram_id)
                    .order_by(AdminActionLog.created_at.asc())
                )
            ).all()
        )
        payments = list(
            (
                await self.session.scalars(
                    select(Payment)
                    .where(Payment.user_id == user.id)
                    .order_by(Payment.created_at.asc())
                )
            ).all()
        )
        return {
            "user": user,
            "questionnaire": user.questionnaire,
            "subscription": user.subscription,
            "payments": payments,
            "events": events,
            "admin_logs": admin_logs,
        }
