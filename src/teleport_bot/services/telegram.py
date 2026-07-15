from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from structlog.stdlib import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class InviteLinkResult:
    sent: bool
    already_member: bool
    invite_link: str | None = None


class TelegramService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_single_use_invite(
        self, chat_id: int | str, user_telegram_id: int
    ) -> InviteLinkResult:
        member = await self.bot.get_chat_member(chat_id, user_telegram_id)
        if member.status in {"member", "administrator", "creator"}:
            logger.info(
                "access delivery stopped",
                reason="user_already_member",
                chat_id=chat_id,
                telegram_id=user_telegram_id,
                member_status=member.status,
            )
            return InviteLinkResult(sent=False, already_member=True)
        logger.info(
            "STEP 5 create invite started",
            chat_id=chat_id,
            telegram_id=user_telegram_id,
        )
        try:
            link = await self.bot.create_chat_invite_link(chat_id, member_limit=1)
        except TelegramBadRequest as exc:
            logger.warning(
                "access delivery stopped",
                reason="telegram_bad_request_create_invite",
                chat_id=chat_id,
                telegram_id=user_telegram_id,
                error=str(exc),
            )
            raise
        if link is None or not link.invite_link:
            logger.warning(
                "access delivery stopped",
                reason="invite_link_empty",
                chat_id=chat_id,
                telegram_id=user_telegram_id,
            )
            raise RuntimeError("invite_link_empty")
        logger.info(
            "STEP 6 invite created",
            chat_id=chat_id,
            telegram_id=user_telegram_id,
            invite_link_present=True,
        )
        try:
            await self.bot.send_message(
                user_telegram_id, f"Ваша одноразовая ссылка: {link.invite_link}"
            )
        except TelegramForbiddenError as exc:
            logger.warning(
                "access delivery stopped",
                reason="telegram_forbidden_send_message",
                chat_id=chat_id,
                telegram_id=user_telegram_id,
                error=str(exc),
            )
            raise
        logger.info(
            "STEP 7 message sent", chat_id=chat_id, telegram_id=user_telegram_id
        )
        return InviteLinkResult(
            sent=True, already_member=False, invite_link=link.invite_link
        )


__all__ = [
    "InviteLinkResult",
    "TelegramBadRequest",
    "TelegramForbiddenError",
    "TelegramService",
]
