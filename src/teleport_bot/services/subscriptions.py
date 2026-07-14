from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from teleport_bot.models.db import Subscription, SubscriptionReminder, User
from teleport_bot.models.enums import EventType, SubscriptionStatus
from teleport_bot.repositories.events import EventRepository
from teleport_bot.repositories.subscriptions import SubscriptionRepository

REMINDER_DAYS = {3: "3_days", 1: "1_day", 0: "today"}


def renew_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Продлить подписку", callback_data="payment:start")]
        ]
    )


class SubscriptionLifecycleService:
    def __init__(self, session: AsyncSession, bot: Any) -> None:
        self.session = session
        self.bot = bot
        self.events = EventRepository(session)

    async def process_daily(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        await self.send_due_reminders(now)
        await self.expire_overdue(now)

    async def send_due_reminders(self, now: datetime) -> None:
        rows = await self.session.scalars(
            select(Subscription)
            .join(Subscription.user)
            .options(selectinload(Subscription.user))
            .where(
                Subscription.status.in_(
                    [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.MANUAL.value]
                ),
                Subscription.expires_at.is_not(None),
            )
        )
        for sub in rows:
            if sub.expires_at is None:
                continue
            days_left = (sub.expires_at.date() - now.date()).days
            reminder_type = REMINDER_DAYS.get(days_left)
            if reminder_type is None:
                continue
            already = await self.session.scalar(
                select(
                    exists().where(
                        SubscriptionReminder.subscription_id == sub.id,
                        SubscriptionReminder.reminder_type == reminder_type,
                    )
                )
            )
            if already:
                continue
            await self.bot.send_message(
                sub.user.telegram_id,
                f"Твоя подписка заканчивается {sub.expires_at.date()}.\n\n"
                "Чтобы не потерять доступ к Телепорту, продли подписку.",
                reply_markup=renew_keyboard(),
            )
            self.session.add(
                SubscriptionReminder(subscription_id=sub.id, reminder_type=reminder_type)
            )
            await self.events.add(
                EventType.SUBSCRIPTION_REMINDER_SENT,
                sub.user,
                {"subscription_id": sub.id, "reminder_type": reminder_type},
            )
            await self.session.flush()

    async def expire_overdue(self, now: datetime) -> None:
        rows = await self.session.scalars(
            select(Subscription)
            .join(Subscription.user)
            .options(selectinload(Subscription.user))
            .where(
                Subscription.status.in_(
                    [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.MANUAL.value]
                ),
                Subscription.expires_at.is_not(None),
                Subscription.expires_at < now,
            )
        )
        for sub in rows:
            sub.status = SubscriptionStatus.EXPIRED.value
            await self.bot.send_message(
                sub.user.telegram_id,
                "Подписка закончилась.\n\nТы всегда можешь вернуться ❤️",
                reply_markup=renew_keyboard(),
            )
            await self.events.add(
                EventType.SUBSCRIPTION_EXPIRED, sub.user, {"subscription_id": sub.id}
            )
        await self.session.flush()


class ManualSubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.events = EventRepository(session)

    async def import_subscription(
        self, telegram_id: int, expires_at: datetime, admin_id: int, comment: str | None = None
    ) -> User:
        from teleport_bot.repositories.users import UserRepository

        repo = UserRepository(self.session)
        user = await repo.get_by_telegram_id(telegram_id)
        if user is None:

            class Tg:
                id: int = telegram_id
                username: str | None = None
                first_name: str = ""
                last_name: str | None = None
                language_code: str | None = None

            user, _ = await repo.upsert_from_telegram(Tg())
        sub = await SubscriptionRepository(self.session).activate_manual(
            user, expires_at, admin_id, activation_source="migration"
        )
        sub.payment_provider = None
        sub.last_payment_at = None
        await self.events.add(
            EventType.SUBSCRIPTION_MIGRATED,
            user,
            {"expires_at": expires_at.isoformat(), "comment": comment},
        )
        return user

    async def extend_manual(self, telegram_id: int, days: int, admin_id: int) -> Subscription:
        from teleport_bot.repositories.users import UserRepository

        user = await UserRepository(self.session).get_by_telegram_id(telegram_id)
        if user is None or user.subscription is None:
            raise ValueError("subscription_not_found")
        base = user.subscription.expires_at or datetime.now(UTC)
        if base < datetime.now(UTC):
            base = datetime.now(UTC)
        user.subscription.expires_at = base + timedelta(days=days)
        user.subscription.status = SubscriptionStatus.MANUAL.value
        await self.events.add(
            EventType.SUBSCRIPTION_EXTENDED_MANUAL,
            user,
            {
                "days": days,
                "admin_id": admin_id,
                "expires_at": user.subscription.expires_at.isoformat(),
            },
        )
        await self.session.flush()
        return user.subscription

    async def cancel(self, telegram_id: int, admin_id: int) -> Subscription:
        from teleport_bot.repositories.users import UserRepository

        user = await UserRepository(self.session).get_by_telegram_id(telegram_id)
        if user is None or user.subscription is None:
            raise ValueError("subscription_not_found")
        user.subscription.status = SubscriptionStatus.CANCELLED.value
        await self.events.add(EventType.SUBSCRIPTION_CANCELLED, user, {"admin_id": admin_id})
        await self.session.flush()
        return user.subscription
