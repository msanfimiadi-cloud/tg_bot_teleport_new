from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from teleport_bot.config.settings import Settings
from teleport_bot.db.base import Base
from teleport_bot.models.db import EventLog, SubscriptionReminder
from teleport_bot.models.enums import EventType, SubscriptionStatus
from teleport_bot.repositories.admin import AdminLogRepository, AdminRepository
from teleport_bot.repositories.settings import SettingsRepository
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.subscriptions import (
    ManualSubscriptionService,
    SubscriptionLifecycleService,
)


@dataclass
class TgUser:
    id: int
    username: str | None
    first_name: str
    last_name: str | None = None
    language_code: str | None = None


class MockBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        self.messages.append((chat_id, text))


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def make_subscription(session, days: int):
    user, _ = await UserRepository(session).upsert_from_telegram(TgUser(100 + days, "u", "User"))
    expires = datetime(2026, 7, 14, 12, tzinfo=UTC) + timedelta(days=days)
    sub = await SubscriptionRepository(session).activate_manual(user, expires, 10)
    return user, sub


@pytest.mark.parametrize("days,reminder_type", [(3, "3_days"), (1, "1_day"), (0, "today")])
async def test_subscription_reminders(session_factory, days: int, reminder_type: str) -> None:
    async with session_factory() as session, session.begin():
        _, sub = await make_subscription(session, days)
        bot = MockBot()
        await SubscriptionLifecycleService(session, bot).send_due_reminders(
            datetime(2026, 7, 14, 9, tzinfo=UTC)
        )
        assert len(bot.messages) == 1
        reminder = (await session.scalars(select(SubscriptionReminder))).one()
        assert reminder.subscription_id == sub.id
        assert reminder.reminder_type == reminder_type


async def test_subscription_reminder_not_duplicated(session_factory) -> None:
    async with session_factory() as session, session.begin():
        await make_subscription(session, 3)
        bot = MockBot()
        service = SubscriptionLifecycleService(session, bot)
        now = datetime(2026, 7, 14, 9, tzinfo=UTC)
        await service.send_due_reminders(now)
        await service.send_due_reminders(now)
        assert len(bot.messages) == 1
        assert len((await session.scalars(select(SubscriptionReminder))).all()) == 1
        events = (await session.scalars(select(EventLog))).all()
        assert [e.event_type for e in events].count(EventType.SUBSCRIPTION_REMINDER_SENT.value) == 1


async def test_subscription_expiration(session_factory) -> None:
    async with session_factory() as session, session.begin():
        _, sub = await make_subscription(session, -1)
        bot = MockBot()
        await SubscriptionLifecycleService(session, bot).expire_overdue(
            datetime(2026, 7, 14, 9, tzinfo=UTC)
        )
        assert sub.status == SubscriptionStatus.EXPIRED.value
        assert len(bot.messages) == 1


async def test_manual_import_and_migration_user(session_factory) -> None:
    async with session_factory() as session, session.begin():
        expires = datetime(2026, 8, 1, tzinfo=UTC)
        user = await ManualSubscriptionService(session).import_subscription(777, expires, 10, "old")
        assert user.subscription is not None
        assert user.subscription.activation_source == "migration"
        assert user.subscription.activated_by == 10
        assert user.subscription.last_payment_at is None
        assert user.subscription.payment_provider is None


async def test_manual_extend_and_cancel(session_factory) -> None:
    async with session_factory() as session, session.begin():
        user, sub = await make_subscription(session, 5)
        old_expires = sub.expires_at
        updated = await ManualSubscriptionService(session).extend_manual(user.telegram_id, 10, 10)
        assert old_expires is not None
        assert updated.expires_at == old_expires + timedelta(days=10)
        cancelled = await ManualSubscriptionService(session).cancel(user.telegram_id, 10)
        assert cancelled.status == SubscriptionStatus.CANCELLED.value


async def test_user_history_and_settings(session_factory) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await make_subscription(session, 5)
        await AdminLogRepository(session).add(
            10, EventType.SUBSCRIPTION_EXTENDED_MANUAL, user.telegram_id
        )
        history = await AdminRepository(session).user_history(user.telegram_id)
        assert history is not None
        assert history["subscription"] is not None
        repo = SettingsRepository(session)
        await repo.set("subscription_duration_days", "45", 10)
        effective = await repo.effective(Settings(subscription_duration_days=30))
        assert effective["subscription_duration_days"] == 45
