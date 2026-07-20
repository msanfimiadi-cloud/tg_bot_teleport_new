from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.enums import ChatType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from teleport_bot.bot.handlers.admin import (
    is_admin,
    parse_expiration_date,
    parse_positive_days,
    parse_telegram_id,
    render_chatid_response,
    send_payment_reminders,
)
from teleport_bot.bot.keyboards.admin import (
    admin_menu,
    payment_reminder_confirm,
    users_pagination,
)
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
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def test_render_chatid_response_for_group() -> None:
    assert render_chatid_response(-100123, "Teleport", ChatType.SUPERGROUP) == (
        "ID этого чата:\n"
        "-100123\n\n"
        "Название:\n"
        "Teleport\n\n"
        "Тип:\n"
        "supergroup"
    )


def test_admin_access_by_telegram_id() -> None:
    settings = Settings(admin_ids="10,20")
    assert is_admin(settings, 10) is True


def test_regular_user_access_denied_by_telegram_id() -> None:
    settings = Settings(admin_ids="10,20")
    assert is_admin(settings, 30) is False


def test_admin_input_validation() -> None:
    assert parse_telegram_id("123") == 123
    assert parse_positive_days("30") == 30
    assert parse_expiration_date("2026-08-01").tzinfo == UTC
    for value in ("", "abc", "-1", "0"):
        with pytest.raises(ValueError):
            parse_telegram_id(value)
    for value in ("0", "-10", "abc", "3651"):
        with pytest.raises(ValueError):
            parse_positive_days(value)
    with pytest.raises(ValueError):
        parse_expiration_date("not-a-date")


async def test_create_subscription(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(1, "one", "One"))
        expires = datetime.now(UTC) + timedelta(days=30)
        subscription = await SubscriptionRepository(session).activate_manual(user, expires, 10)
        assert subscription.status == SubscriptionStatus.MANUAL.value
        assert subscription.expires_at == expires
        assert subscription.activated_by == 10
        assert subscription.activation_source == "manual"


async def test_update_subscription(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(2, "two", "Two"))
        repo = SubscriptionRepository(session)
        await repo.activate_manual(user, datetime.now(UTC) + timedelta(days=10))
        updated_expires = datetime.now(UTC) + timedelta(days=40)
        updated = await repo.activate_manual(user, updated_expires)
        rows = (await session.scalars(select(Subscription))).all()
        assert len(rows) == 1
        assert updated.expires_at == updated_expires


async def test_manual_activation_is_logged(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        await AdminLogRepository(session).add(
            10, AdminAction.MANUAL_SUBSCRIPTION_ACTIVATED, 1, {"expires_at": "2026-08-01"}
        )
        row = (await session.scalars(select(AdminActionLog))).one()
        assert row.action == AdminAction.MANUAL_SUBSCRIPTION_ACTIVATED.value


async def test_manual_link_success_is_logged(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        await AdminLogRepository(session).add(10, AdminAction.MANUAL_LINK_SENT, 1)
        row = (await session.scalars(select(AdminActionLog))).one()
        assert row.action == AdminAction.MANUAL_LINK_SENT.value


async def test_telegram_api_error_is_logged(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        await AdminLogRepository(session).add(
            10, AdminAction.TELEGRAM_API_ERROR, 1, {"error": "boom"}
        )
        row = (await session.scalars(select(AdminActionLog))).one()
        assert row.payload["error"] == "boom"


async def test_user_search(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        await UserRepository(session).upsert_from_telegram(TgUser(100, "needle", "Alice"))
        await UserRepository(session).upsert_from_telegram(TgUser(200, "other", "Bob"))
        by_username = await AdminRepository(session).users(query="needle")
        by_id = await AdminRepository(session).users(query="200")
        by_name = await AdminRepository(session).users(query="ali")
        assert [u.telegram_id for u in by_username] == [100]
        assert [u.telegram_id for u in by_id] == [200]
        assert [u.telegram_id for u in by_name] == [100]
        assert await AdminRepository(session).users_count() == 2
        assert await AdminRepository(session).users_count(query="needle") == 1


def test_users_pagination_buttons() -> None:
    first = users_pagination(1, 3).inline_keyboard[0]
    middle = users_pagination(2, 3).inline_keyboard[0]
    last = users_pagination(3, 3).inline_keyboard[0]

    assert [button.callback_data for button in first] == ["admin:users:1", "admin:users:2"]
    assert [button.callback_data for button in middle] == [
        "admin:users:1",
        "admin:users:2",
        "admin:users:3",
    ]
    assert [button.callback_data for button in last] == ["admin:users:2", "admin:users:3"]


async def test_all_user_telegram_ids(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        await UserRepository(session).upsert_from_telegram(TgUser(101, "one", "One"))
        await UserRepository(session).upsert_from_telegram(TgUser(202, "two", "Two"))

        assert await UserRepository(session).all_telegram_ids() == [101, 202]


async def test_payment_reminder_is_sent_with_payment_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.messages: list[tuple[int, str, Any]] = []

        async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
            self.messages.append((chat_id, text, kwargs.get("reply_markup")))

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("teleport_bot.bot.handlers.admin.asyncio.sleep", no_sleep)
    bot = FakeBot()

    sent, failed = await send_payment_reminders(bot, [101, 202])  # type: ignore[arg-type]

    assert (sent, failed) == (2, 0)
    assert [message[0] for message in bot.messages] == [101, 202]
    button = bot.messages[0][2].inline_keyboard[0][0]
    assert button.callback_data == "payment:renew"


def test_payment_reminder_admin_buttons_require_confirmation() -> None:
    menu_callbacks = {
        button.callback_data for row in admin_menu().inline_keyboard for button in row
    }
    assert "admin:payment_reminder" in menu_callbacks
    confirm_button = payment_reminder_confirm(12).inline_keyboard[0][0]
    assert confirm_button.callback_data == "admin:payment_reminder:confirm_all"
    assert "12" in confirm_button.text


async def test_stats(session_factory: Any) -> None:
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


def test_admin_log_payload_never_stores_full_invite_link() -> None:
    from teleport_bot.repositories.events import safe_log_payload

    payload = safe_log_payload({"invite_link": "https://t.me/+secret", "chat_id": -100})

    assert "invite_link" not in payload
    assert payload["invite_link_length"] == len("https://t.me/+secret")
    assert payload["chat_id"] == -100
    assert "invite_link_sha256" in payload
