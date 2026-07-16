from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from sqlalchemy import delete, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.stdlib import get_logger

from teleport_bot.config.settings import Settings
from teleport_bot.models.db import AdminChatMessageDraft
from teleport_bot.models.enums import AdminAction, AdminChatMessageDraftStatus
from teleport_bot.repositories.admin import AdminLogRepository
from teleport_bot.services.telegram import TelegramService

logger = get_logger(__name__)
TELEGRAM_MESSAGE_LIMIT = 4096
ALLOWED_HTML_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "a",
    "code",
    "pre",
    "blockquote",
}


class MessageValidationError(ValueError):
    pass


class _TelegramHTMLValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.error: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_HTML_TAGS:
            self.error = f"HTML-тег <{tag}> не поддерживается."
            return
        if tag == "a" and not any(name == "href" and value for name, value in attrs):
            self.error = "HTML-ссылка <a> должна содержать href."
            return
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in ALLOWED_HTML_TAGS:
            self.error = f"HTML-тег </{tag}> не поддерживается."
            return
        if not self.stack or self.stack[-1] != tag:
            self.error = f"HTML-тег </{tag}> закрыт некорректно."
            return
        self.stack.pop()

    def validate(self, text: str) -> None:
        try:
            self.feed(text)
            self.close()
        except Exception as exc:  # HTMLParser can raise on malformed declarations.
            raise MessageValidationError("Некорректная HTML-разметка.") from exc
        if self.error:
            raise MessageValidationError(self.error)
        if self.stack:
            raise MessageValidationError(f"HTML-тег <{self.stack[-1]}> не закрыт.")


@dataclass(frozen=True)
class PublishResult:
    draft_id: int
    message_id: int


class AdminChatPublisherService:
    def __init__(
        self, session: AsyncSession, telegram: TelegramService, settings: Settings
    ) -> None:
        self.session = session
        self.telegram = telegram
        self.settings = settings

    @staticmethod
    def text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @classmethod
    def validate_text(cls, text: str | None) -> str:
        normalized = text or ""
        if not normalized.strip():
            raise MessageValidationError("Сообщение не может быть пустым.")
        if len(normalized) > TELEGRAM_MESSAGE_LIMIT:
            raise MessageValidationError(
                "Сообщение слишком длинное: "
                f"{len(normalized)} из {TELEGRAM_MESSAGE_LIMIT} символов."
            )
        _TelegramHTMLValidator().validate(normalized)
        return normalized

    async def create_draft(self, admin_telegram_id: int, text: str) -> AdminChatMessageDraft:
        text = self.validate_text(text)
        draft = AdminChatMessageDraft(
            admin_telegram_id=admin_telegram_id,
            text=text,
            text_hash=self.text_hash(text),
            status=AdminChatMessageDraftStatus.DRAFT.value,
        )
        self.session.add(draft)
        await self.session.flush()
        await AdminLogRepository(self.session).add(
            admin_telegram_id,
            AdminAction.CHAT_MESSAGE_DRAFT_CREATED,
            payload={
                "draft_id": draft.id,
                "text_length": len(text),
                "text_sha256": draft.text_hash,
            },
        )
        return draft

    async def replace_text(
        self, draft_id: int, admin_telegram_id: int, text: str
    ) -> AdminChatMessageDraft:
        draft = await self.get_draft_for_admin(draft_id, admin_telegram_id)
        text = self.validate_text(text)
        draft.text = text
        draft.text_hash = self.text_hash(text)
        draft.status = AdminChatMessageDraftStatus.DRAFT.value
        draft.error_code = None
        await self.session.flush()
        return draft

    async def get_draft_for_admin(
        self, draft_id: int, admin_telegram_id: int
    ) -> AdminChatMessageDraft:
        draft = await self.session.get(AdminChatMessageDraft, draft_id)
        if draft is None or draft.admin_telegram_id != admin_telegram_id:
            raise PermissionError("draft_not_found")
        return draft

    async def cancel(self, draft_id: int, admin_telegram_id: int) -> None:
        draft = await self.get_draft_for_admin(draft_id, admin_telegram_id)
        draft.status = AdminChatMessageDraftStatus.CANCELLED.value
        await AdminLogRepository(self.session).add(
            admin_telegram_id,
            AdminAction.CHAT_MESSAGE_CANCELLED,
            payload={
                "draft_id": draft.id,
                "text_length": len(draft.text),
                "text_sha256": draft.text_hash,
            },
        )

    def _chat_id(self) -> int | str:
        chat_id = self.settings.private_chat_id
        if chat_id in (None, "", 0, "0"):
            raise RuntimeError("private_chat_id_missing")
        return chat_id if isinstance(chat_id, int) else str(chat_id)

    async def cleanup_finished_drafts(self, older_than: datetime) -> int:
        result = await self.session.execute(
            delete(AdminChatMessageDraft).where(
                AdminChatMessageDraft.status.in_(
                    {
                        AdminChatMessageDraftStatus.SENT.value,
                        AdminChatMessageDraftStatus.CANCELLED.value,
                    }
                ),
                AdminChatMessageDraft.updated_at < older_than,
            )
        )
        cursor_result = result if isinstance(result, CursorResult) else None
        return cursor_result.rowcount if cursor_result is not None else 0

    async def publish(self, draft_id: int, admin_telegram_id: int) -> PublishResult:
        draft = await self.get_draft_for_admin(draft_id, admin_telegram_id)
        if draft.status == AdminChatMessageDraftStatus.SENT.value and draft.telegram_message_id:
            return PublishResult(draft.id, draft.telegram_message_id)
        if draft.status == AdminChatMessageDraftStatus.SENDING.value:
            raise RuntimeError("draft_already_sending")
        publishable = {
            AdminChatMessageDraftStatus.DRAFT.value,
            AdminChatMessageDraftStatus.FAILED.value,
        }
        if draft.status not in publishable:
            raise RuntimeError("draft_not_publishable")
        self.validate_text(draft.text)
        chat_id = self._chat_id()
        result = await self.session.execute(
            update(AdminChatMessageDraft)
            .where(
                AdminChatMessageDraft.id == draft.id,
                AdminChatMessageDraft.admin_telegram_id == admin_telegram_id,
                AdminChatMessageDraft.status.in_(publishable),
            )
            .values(status=AdminChatMessageDraftStatus.SENDING.value)
        )
        cursor_result = result if isinstance(result, CursorResult) else None
        if cursor_result is None or cursor_result.rowcount != 1:
            await self.session.refresh(draft)
            if draft.status == AdminChatMessageDraftStatus.SENT.value and draft.telegram_message_id:
                return PublishResult(draft.id, draft.telegram_message_id)
            raise RuntimeError("draft_already_sending")
        draft.status = AdminChatMessageDraftStatus.SENDING.value
        try:
            msg = await self.telegram.send_admin_chat_message(chat_id, draft.text)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as exc:
            await self._mark_failed(draft, admin_telegram_id, exc)
            raise
        except TelegramAPIError as exc:
            await self._mark_failed(draft, admin_telegram_id, exc)
            raise
        draft.status = AdminChatMessageDraftStatus.SENT.value
        draft.telegram_message_id = int(msg.message_id)
        draft.sent_at = datetime.now(UTC)
        await AdminLogRepository(self.session).add(
            admin_telegram_id,
            AdminAction.CHAT_MESSAGE_PUBLISHED,
            payload={
                "draft_id": draft.id,
                "private_chat_id": chat_id,
                "telegram_message_id": draft.telegram_message_id,
                "text_length": len(draft.text),
                "text_sha256": draft.text_hash,
            },
        )
        return PublishResult(draft.id, draft.telegram_message_id)

    async def _mark_failed(
        self, draft: AdminChatMessageDraft, admin_id: int, exc: Exception
    ) -> None:
        code = type(exc).__name__
        draft.status = AdminChatMessageDraftStatus.FAILED.value
        draft.error_code = code
        logger.warning("admin chat publish failed", error_code=code, draft_id=draft.id)
        await AdminLogRepository(self.session).add(
            admin_id,
            AdminAction.CHAT_MESSAGE_PUBLISH_FAILED,
            payload={
                "draft_id": draft.id,
                "error_code": code,
                "text_length": len(draft.text),
                "text_sha256": draft.text_hash,
            },
        )
