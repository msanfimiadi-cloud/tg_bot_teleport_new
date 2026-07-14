from aiogram import Bot
from structlog.stdlib import get_logger

from teleport_bot.models.db import Questionnaire, User
from teleport_bot.models.enums import EventType
from teleport_bot.repositories.events import EventRepository

logger = get_logger(__name__)


class AdminNotifier:
    def __init__(self, bot: Bot, admin_ids: tuple[int, ...], events: EventRepository) -> None:
        self.bot = bot
        self.admin_ids = admin_ids
        self.events = events

    async def _send(self, text: str, user: User) -> None:
        for admin_id in self.admin_ids:
            try:
                await self.bot.send_message(admin_id, text)
            except Exception as exc:
                logger.exception("admin_notification_failed", admin_id=admin_id, user_id=user.id)
                await self.events.add(
                    EventType.ADMIN_NOTIFICATION_FAILED,
                    user,
                    {"admin_id": admin_id, "error": exc.__class__.__name__},
                )

    async def user_started(self, user: User) -> None:
        await self._send(f"Новый пользователь: {user.telegram_id} @{user.username or '-'}", user)

    async def questionnaire_completed(self, user: User, questionnaire: Questionnaire) -> None:
        text = (
            "Анкета подтверждена\n"
            f"Telegram ID: {user.telegram_id}\nUsername: @{user.username}\nИмя: {user.first_name}\n"
            f"1: {questionnaire.name_and_age}\n2: {questionnaire.what_annoys}\n"
            f"3: {questionnaire.what_is_important}\n4: {questionnaire.self_definition}\n"
            f"5: {questionnaire.intention}\n"
            f"Дата: {questionnaire.completed_at}\nСтатус: {user.funnel_status}"
        )
        await self._send(text, user)

    async def payment_stage_reached(self, user: User) -> None:
        await self._send(f"Пользователь дошёл до оплаты: {user.telegram_id}", user)
