from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from teleport_bot.models.db import AdminActionLog, Questionnaire, Subscription, User
from teleport_bot.models.enums import AdminAction, QuestionnaireStatus, SubscriptionStatus


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
            payload=payload or {},
        )
        self.session.add(row)
        await self.session.flush()
        return row


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
            conditions = [
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
