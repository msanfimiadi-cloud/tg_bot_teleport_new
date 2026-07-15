from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.stdlib import get_logger

from teleport_bot.models.enums import AdminAction
from teleport_bot.repositories.admin import AdminLogRepository
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.telegram import InviteLinkResult, TelegramService

logger = get_logger(__name__)


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
            logger.warning(
                "access service stopped",
                reason="user_not_found",
                telegram_id=target_telegram_id,
            )
            raise ValueError("user_not_found")
        if not SubscriptionRepository.is_active(user.subscription):
            logger.warning(
                "access service stopped",
                reason="subscription_inactive",
                user_id=user.id,
                telegram_id=target_telegram_id,
                subscription_status=(
                    user.subscription.status if user.subscription else None
                ),
                subscription_expires_at=(
                    user.subscription.expires_at.isoformat()
                    if user.subscription and user.subscription.expires_at
                    else None
                ),
            )
            raise PermissionError("subscription_inactive")
        logger.info(
            "access service subscription verified",
            user_id=user.id,
            telegram_id=target_telegram_id,
            subscription_status=user.subscription.status if user.subscription else None,
            subscription_expires_at=(
                user.subscription.expires_at.isoformat()
                if user.subscription and user.subscription.expires_at
                else None
            ),
        )
        return await self.telegram.send_single_use_invite(
            private_chat_id, target_telegram_id
        )

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
            result = await self.telegram.send_single_use_invite(
                private_chat_id, target_telegram_id
            )
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
                {"invite_link": result.invite_link},
            )
        return result
