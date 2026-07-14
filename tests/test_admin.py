from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from teleport_bot.bot.handlers.admin import is_admin
from teleport_bot.config.settings import Settings
from teleport_bot.db.base import Base
from teleport_bot.models.db import AdminActionLog, Subscription
from teleport_bot.models.enums import AdminAction, SubscriptionStatus
from teleport_bot.repositories.admin import AdminLogRepository, AdminRepository
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.questionnaire import complete


@dataclass
class TgUser:
    id: int
    username: str | None
    first_name: str
    last_name: str | None = None
    language_code: str | None = None


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def test_admin_access_by_telegram_id() -> None:
    settings = Settings(admin_ids="10,20")
    assert is_admin(settings, 10) is True


def test_regular_user_access_denied_by_telegram_id() -> None:
    settings = Settings(admin_ids="10,20")
    assert is_admin(settings, 30) is False


async def test_create_subscription(session_factory) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(1, "one", "One"))
        expires = datetime.now(UTC) + timedelta(days=30)
        subscription = await SubscriptionRepository(session).activate_manual(user, expires, 10)
        assert subscription.status == SubscriptionStatus.MANUAL.value
        assert subscription.expires_at == expires
        assert subscription.activated_by == 10
        assert subscription.activation_source == "manual"


async def test_update_subscription(session_factory) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(2, "two", "Two"))
        repo = SubscriptionRepository(session)
        await repo.activate_manual(user, datetime.now(UTC) + timedelta(days=10))
        updated_expires = datetime.now(UTC) + timedelta(days=40)
        updated = await repo.activate_manual(user, updated_expires)
        rows = (await session.scalars(select(Subscription))).all()
        assert len(rows) == 1
        assert updated.expires_at == updated_expires


async def test_manual_activation_is_logged(session_factory) -> None:
    async with session_factory() as session, session.begin():
        await AdminLogRepository(session).add(
            10, AdminAction.MANUAL_SUBSCRIPTION_ACTIVATED, 1, {"expires_at": "2026-08-01"}
        )
        row = (await session.scalars(select(AdminActionLog))).one()
        assert row.action == AdminAction.MANUAL_SUBSCRIPTION_ACTIVATED.value


async def test_manual_link_success_is_logged(session_factory) -> None:
    async with session_factory() as session, session.begin():
        await AdminLogRepository(session).add(10, AdminAction.MANUAL_LINK_SENT, 1)
        row = (await session.scalars(select(AdminActionLog))).one()
        assert row.action == AdminAction.MANUAL_LINK_SENT.value


async def test_telegram_api_error_is_logged(session_factory) -> None:
    async with session_factory() as session, session.begin():
        await AdminLogRepository(session).add(
            10, AdminAction.TELEGRAM_API_ERROR, 1, {"error": "boom"}
        )
        row = (await session.scalars(select(AdminActionLog))).one()
        assert row.payload["error"] == "boom"


async def test_user_search(session_factory) -> None:
    async with session_factory() as session, session.begin():
        await UserRepository(session).upsert_from_telegram(TgUser(100, "needle", "Alice"))
        await UserRepository(session).upsert_from_telegram(TgUser(200, "other", "Bob"))
        by_username = await AdminRepository(session).users(query="needle")
        by_id = await AdminRepository(session).users(query="200")
        by_name = await AdminRepository(session).users(query="ali")
        assert [u.telegram_id for u in by_username] == [100]
        assert [u.telegram_id for u in by_id] == [200]
        assert [u.telegram_id for u in by_name] == [100]


async def test_stats(session_factory) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(300, "stats", "Stat"))
        user.questionnaire.name_and_age = "Stat 30"
        user.questionnaire.what_annoys = "long enough"
        user.questionnaire.what_is_important = "long enough"
        user.questionnaire.self_definition = "long enough"
        user.questionnaire.intention = "long enough"
        assert complete(user, user.questionnaire) is True
        await SubscriptionRepository(session).activate_manual(
            user, datetime.now(UTC) + timedelta(days=30)
        )
        stats = await AdminRepository(session).stats()
        assert stats["total_users"] == 1
        assert stats["completed_questionnaires"] == 1
        assert stats["active_subscriptions"] == 1
