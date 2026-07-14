from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError


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
            return InviteLinkResult(sent=False, already_member=True)
        link = await self.bot.create_chat_invite_link(chat_id, member_limit=1)
        await self.bot.send_message(
            user_telegram_id, f"Ваша одноразовая ссылка: {link.invite_link}"
        )
        return InviteLinkResult(sent=True, already_member=False, invite_link=link.invite_link)


__all__ = ["InviteLinkResult", "TelegramAPIError", "TelegramService"]
