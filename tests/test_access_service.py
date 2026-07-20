from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from teleport_bot.db.base import Base
from teleport_bot.models.db import AdminActionLog
from teleport_bot.models.enums import AdminAction
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.access import AccessService
from teleport_bot.services.telegram import InviteLinkResult, TelegramService


@dataclass
class TgUser:
    id: int
    username: str | None
    first_name: str
    last_name: str | None = None
    language_code: str | None = None


class FakeTelegramService:
    async def send_single_use_invite(
        self,
        chat_id: int | str,
        user_telegram_id: int,
        *,
        invite_link_ttl_hours: int | None = None,
    ) -> InviteLinkResult:
        return InviteLinkResult(
            sent=True,
            already_member=False,
            invite_link=f"https://t.me/+invite-{user_telegram_id}-{chat_id}",
        )


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_manual_invite_logs_after_success_inside_open_transaction(
    session_factory: Any,
) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(
            TgUser(12345, "target", "Target")
        )
        subscription = await SubscriptionRepository(session).activate_manual(
            user,
            datetime.now(UTC) + timedelta(days=30),
            activated_by=10,
        )
        subscription.expires_at = None

    async with session_factory() as session, session.begin():
        telegram = cast(TelegramService, FakeTelegramService())
        result = await AccessService(session, telegram).send_manual_invite(
            admin_id=10,
            target_telegram_id=12345,
            private_chat_id=-100,
        )

        assert result.sent is True
        row = (await session.scalars(select(AdminActionLog))).one()
        assert row.action == AdminAction.MANUAL_LINK_SENT.value
        assert row.admin_id == 10
        assert row.target_user_id == 12345
        assert row.payload["invite_link_sha256"]
        assert "invite_link" not in row.payload


async def test_invite_link_uses_configured_ttl() -> None:
    class FakeBot:
        expire_date: datetime | None = None

        async def get_chat_member(self, chat_id: int, user_id: int) -> object:
            return SimpleNamespace(status="left")

        async def create_chat_invite_link(self, chat_id: int, **kwargs: object) -> object:
            self.expire_date = cast(datetime, kwargs.get("expire_date"))
            return SimpleNamespace(invite_link="https://t.me/+temporary")

        async def send_message(self, chat_id: int, text: str) -> None:
            return None

    bot = FakeBot()
    before = datetime.now(UTC) + timedelta(hours=23, minutes=59)
    await TelegramService(cast(Any, bot)).send_single_use_invite(
        -100, 12345, invite_link_ttl_hours=24
    )
    after = datetime.now(UTC) + timedelta(hours=24, minutes=1)
    assert bot.expire_date is not None
    assert before <= bot.expire_date <= after
