from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from structlog.stdlib import get_logger

from teleport_bot.config.settings import Settings
from teleport_bot.models.db import Questionnaire, User
from teleport_bot.models.enums import EventType, QuestionnaireStatus
from teleport_bot.services.admin_notifications import AdminNotifier

logger = get_logger(__name__)


PUBLIC_WELCOME_TEXT = (
    "🎉 Добро пожаловать в «Телепорт»!\n\n"
    "Рады видеть тебя среди нас.\n\n"
    "Теперь ты можешь:\n\n"
    "• знакомиться с участниками;\n"
    "• общаться в чате;\n"
    "• участвовать в еженедельных кругах;\n"
    "• задавать вопросы и получать поддержку.\n\n"
    "Не стесняйся проявляться и быть собой ❤️"
)


def render_public_questionnaire(user: User, questionnaire: Questionnaire) -> str:
    return (
        "Новая анкета участника\n"
        f"Telegram ID: {user.telegram_id}\nUsername: @{user.username or '-'}\n"
        f"Имя: {user.first_name}\n"
        f"1: {questionnaire.name_and_age}\n2: {questionnaire.what_annoys}\n"
        f"3: {questionnaire.what_is_important}\n4: {questionnaire.self_definition}\n"
        f"5: {questionnaire.intention}\nДата: {questionnaire.completed_at}"
    )


async def publish_questionnaire_and_send_welcome(
    bot: Bot | Any,
    settings: Settings,
    events: Any,
    user: User,
    questionnaire: Questionnaire,
) -> bool:
    """Publish a questionnaire to the private group and send the one-time public welcome."""
    if user.welcome_message_sent_at is not None:
        return False
    if questionnaire.status != QuestionnaireStatus.COMPLETED.value:
        return False
    if settings.private_chat_id is None:
        await events.add(
            EventType.PUBLIC_WELCOME_FAILED,
            user,
            {"reason": "private_chat_id_not_configured"},
        )
        await AdminNotifier(bot, settings.admin_telegram_ids, events)._send(
            f"Не удалось отправить приветствие: PRIVATE_CHAT_ID не настроен ({user.telegram_id})",
            user,
        )
        return False

    try:
        await bot.send_message(
            settings.private_chat_id, render_public_questionnaire(user, questionnaire)
        )
    except Exception as exc:
        logger.warning(
            "questionnaire_publication_failed",
            user_id=user.id,
            error=exc.__class__.__name__,
        )
        await events.add(
            EventType.QUESTIONNAIRE_PUBLICATION_FAILED,
            user,
            {"error": exc.__class__.__name__},
        )
        await AdminNotifier(bot, settings.admin_telegram_ids, events)._send(
            f"Не удалось опубликовать анкету: {user.telegram_id}", user
        )
        return False

    try:
        await bot.send_message(settings.private_chat_id, PUBLIC_WELCOME_TEXT)
    except Exception as exc:
        logger.warning("public_welcome_failed", user_id=user.id, error=exc.__class__.__name__)
        await events.add(EventType.PUBLIC_WELCOME_FAILED, user, {"error": exc.__class__.__name__})
        await AdminNotifier(bot, settings.admin_telegram_ids, events)._send(
            f"Не удалось отправить приветствие в группу: {user.telegram_id}", user
        )
        return False

    user.welcome_message_sent_at = datetime.now(UTC)
    await events.add(EventType.PUBLIC_WELCOME_SENT, user)
    return True
