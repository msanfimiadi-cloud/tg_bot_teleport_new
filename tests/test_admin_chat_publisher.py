from typing import Any

import pytest
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from teleport_bot.bot.keyboards.admin import admin_menu
from teleport_bot.config.settings import Settings
from teleport_bot.db.base import Base
from teleport_bot.models.db import AdminActionLog
from teleport_bot.models.enums import AdminAction, AdminChatMessageDraftStatus
from teleport_bot.services.admin_chat_publisher import (
    TELEGRAM_MESSAGE_LIMIT,
    AdminChatPublisherService,
    MessageValidationError,
)


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[tuple[int | str, str]] = []
        self.exc: Exception | None = None

    async def send_admin_chat_message(self, chat_id: int | str, text: str) -> FakeMessage:
        if self.exc:
            raise self.exc
        self.sent.append((chat_id, text))
        return FakeMessage(len(self.sent))


def test_admin_menu_has_chat_publish_button() -> None:
    markup = admin_menu()
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert any(
        b.text == "✍️ Написать сообщение в чат" and b.callback_data == "admin:chat_message:start"
        for b in buttons
    )


def test_empty_too_long_and_bad_html_are_rejected() -> None:
    with pytest.raises(MessageValidationError):
        AdminChatPublisherService.validate_text("   ")
    with pytest.raises(MessageValidationError):
        AdminChatPublisherService.validate_text("x" * (TELEGRAM_MESSAGE_LIMIT + 1))
    with pytest.raises(MessageValidationError):
        AdminChatPublisherService.validate_text("<b>not closed")


async def test_draft_preview_does_not_send_before_confirmation(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        fake = FakeTelegram()
        service = AdminChatPublisherService(session, fake, Settings(private_chat_id=-100))  # type: ignore[arg-type]
        draft = await service.create_draft(10, "Привет <b>чат</b>\nhttps://example.com")
        assert draft.status == AdminChatMessageDraftStatus.DRAFT.value
        assert fake.sent == []


async def test_publish_sends_to_private_chat_and_audits_without_full_text(
    session_factory: Any,
) -> None:
    async with session_factory() as session, session.begin():
        fake = FakeTelegram()
        service = AdminChatPublisherService(session, fake, Settings(private_chat_id=-100))  # type: ignore[arg-type]
        draft = await service.create_draft(10, "Личный текст")
        result = await service.publish(draft.id, 10)
        assert result.message_id == 1
        assert fake.sent == [(-100, "Личный текст")]
        rows = (await session.scalars(select(AdminActionLog))).all()
        published = next(r for r in rows if r.action == AdminAction.CHAT_MESSAGE_PUBLISHED.value)
        assert published.payload["telegram_message_id"] == 1
        assert published.payload["text_length"] == len("Личный текст")
        assert "Личный текст" not in str(published.payload)


async def test_cancel_and_replace_text(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        fake = FakeTelegram()
        service = AdminChatPublisherService(session, fake, Settings(private_chat_id=-100))  # type: ignore[arg-type]
        draft = await service.create_draft(10, "old")
        draft = await service.replace_text(draft.id, 10, "new")
        assert draft.text == "new"
        await service.cancel(draft.id, 10)
        assert draft.status == AdminChatMessageDraftStatus.CANCELLED.value
        assert fake.sent == []


async def test_missing_private_chat_is_safe_error(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        service = AdminChatPublisherService(session, FakeTelegram(), Settings(private_chat_id=0))  # type: ignore[arg-type]
        draft = await service.create_draft(10, "text")
        with pytest.raises(RuntimeError, match="private_chat_id_missing"):
            await service.publish(draft.id, 10)


async def test_telegram_error_marks_failed_and_retry_keeps_text(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        fake = FakeTelegram()
        fake.exc = TelegramForbiddenError(method="sendMessage", message="bot is not a member")  # type: ignore[arg-type]
        service = AdminChatPublisherService(session, fake, Settings(private_chat_id=-100))  # type: ignore[arg-type]
        draft = await service.create_draft(10, "retry me")
        with pytest.raises(TelegramForbiddenError):
            await service.publish(draft.id, 10)
        assert draft.status == AdminChatMessageDraftStatus.FAILED.value
        assert draft.text == "retry me"
        row = (
            await session.scalars(
                select(AdminActionLog).where(
                    AdminActionLog.action == AdminAction.CHAT_MESSAGE_PUBLISH_FAILED.value
                )
            )
        ).one()
        assert row.payload["error_code"] == "TelegramForbiddenError"
        assert "retry me" not in str(row.payload)


async def test_second_publish_after_success_does_not_duplicate(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        fake = FakeTelegram()
        service = AdminChatPublisherService(session, fake, Settings(private_chat_id=-100))  # type: ignore[arg-type]
        draft = await service.create_draft(10, "once")
        await service.publish(draft.id, 10)
        await service.publish(draft.id, 10)
        assert fake.sent == [(-100, "once")]


async def test_other_admin_cannot_publish_foreign_draft(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        fake = FakeTelegram()
        service = AdminChatPublisherService(session, fake, Settings(private_chat_id=-100))  # type: ignore[arg-type]
        draft = await service.create_draft(10, "secret")
        with pytest.raises(PermissionError):
            await service.publish(draft.id, 20)
        assert fake.sent == []
