from aiogram import Bot
from structlog.stdlib import get_logger

from teleport_bot.models.db import Payment, Questionnaire, User
from teleport_bot.models.enums import EventType
from teleport_bot.repositories.events import EventRepository
from teleport_bot.services.formatting import escape_html
from teleport_bot.services.referrals import ReferralService

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
        await self._send(
            f"Новый пользователь: {user.telegram_id} @{escape_html(user.username or '-')}", user
        )

    async def questionnaire_completed(self, user: User, questionnaire: Questionnaire) -> None:
        attr = await ReferralService(self.events.session)._attr(user.id)
        if attr and attr.partner.username:
            partner_text = (
                f"{escape_html(attr.partner.display_name)} / @{escape_html(attr.partner.username)}"
            )
        else:
            partner_text = escape_html(attr.partner.display_name) if attr else "не указан"
        text = (
            "✅ Анкета сохранена\n"
            f"Telegram ID: {user.telegram_id}\nUsername: @{escape_html(user.username)}\n"
            f"Имя: {escape_html(user.first_name)}\n"
            f"1: {escape_html(questionnaire.name_and_age)}\n"
            f"2: {escape_html(questionnaire.what_annoys)}\n"
            f"3: {escape_html(questionnaire.what_is_important)}\n"
            f"4: {escape_html(questionnaire.self_definition)}\n"
            f"5: {escape_html(questionnaire.intention)}\n"
            f"Дата: {questionnaire.completed_at}\nСтатус: {user.funnel_status}\n"
            f"Партнёр: {partner_text}"
        )
        await self._send(text, user)

    async def payment_stage_reached(self, user: User) -> None:
        await self._send(f"Пользователь дошёл до оплаты: {user.telegram_id}", user)

    async def payment_email_requested(self, user: User) -> None:
        await self._send(
            "Бот запросил email для оплаты\n"
            f"Telegram ID: {user.telegram_id}\n"
            f"Username: @{escape_html(user.username or '-')}",
            user,
        )

    async def payment_email_saved(self, user: User) -> None:
        await self._send(
            "Email для оплаты сохранён\n"
            f"Telegram ID: {user.telegram_id}\n"
            f"Username: @{escape_html(user.username or '-')}",
            user,
        )

    async def payment_link_sent(self, user: User, payment: Payment, *, tracked: bool) -> None:
        await self._send(
            "Ссылка на оплату отправлена\n"
            f"Telegram ID: {user.telegram_id}\n"
            f"Сумма: {payment.amount} {payment.currency}\n"
            f"Отслеживание перехода: {'включено' if tracked else 'недоступно'}",
            user,
        )

    async def payment_link_opened(self, user: User, payment: Payment) -> None:
        await self._send(
            "Пользователь перешёл по ссылке оплаты\n"
            f"Telegram ID: {user.telegram_id}\n"
            f"Сумма: {payment.amount} {payment.currency}",
            user,
        )

    async def payment_succeeded(self, user: User, payment: Payment) -> None:
        expires_at = user.subscription.expires_at if user.subscription else None
        text = (
            "✅ Оплата подтверждена\n"
            f"Telegram ID: {user.telegram_id}\n"
            f"Сумма: {payment.amount} {payment.currency}"
        )
        if expires_at:
            text += f"\nПодписка действует до: {expires_at:%d.%m.%Y}"
        await self._send(text, user)

    async def access_delivered(self, user: User, *, already_member: bool) -> None:
        await self._send(
            (
                "Пользователь уже состоит в Telegram-чате\n"
                if already_member
                else "Ссылка в Telegram-чат отправлена\n"
            )
            + f"Telegram ID: {user.telegram_id}",
            user,
        )

    async def payment_creation_failed(
        self,
        user: User,
        *,
        status: int,
        error_code: str | None = None,
        parameter: str | None = None,
    ) -> None:
        text = (
            "Ошибка создания платежа YooKassa\n"
            f"Telegram ID: {user.telegram_id}\n"
            f"HTTP status: {status}\n"
            f"Code: {error_code or '-'}\n"
            f"Parameter: {parameter or '-'}"
        )
        await self._send(text, user)
