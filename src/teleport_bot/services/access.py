from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.models.enums import AdminAction
from teleport_bot.repositories.admin import AdminLogRepository
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.telegram import InviteLinkResult, TelegramService


class AccessService:
    def __init__(self, session: AsyncSession, telegram: TelegramService) -> None:
        self.session = session
        self.telegram = telegram

    async def send_paid_invite(
        self,
        target_telegram_id: int,
        private_chat_id: int | str,
    ) -> InviteLinkResult:
        user = await UserRepository(self.session).get_by_telegram_id(target_telegram_id)
        if user is None:
            raise ValueError("user_not_found")
        if not SubscriptionRepository.is_active(user.subscription):
            raise PermissionError("subscription_inactive")
        return await self.telegram.send_single_use_invite(private_chat_id, target_telegram_id)

    async def send_manual_invite(
        self,
        admin_id: int,
        target_telegram_id: int,
        private_chat_id: int | str,
    ) -> InviteLinkResult:
        user = await UserRepository(self.session).get_by_telegram_id(target_telegram_id)
        if user is None:
            raise ValueError("user_not_found")
        if not SubscriptionRepository.is_active(user.subscription):
            raise PermissionError("subscription_inactive")
        try:
            result = await self.telegram.send_single_use_invite(private_chat_id, target_telegram_id)
        except TelegramAPIError as exc:
            await AdminLogRepository(self.session).add(
                admin_id,
                AdminAction.TELEGRAM_API_ERROR,
                target_telegram_id,
                {"error": str(exc)},
            )
            raise
        if result.sent:
            await AdminLogRepository(self.session).add(
                admin_id,
                AdminAction.MANUAL_LINK_SENT,
                target_telegram_id,
                {"link": result.invite_link},
            )
        return result
