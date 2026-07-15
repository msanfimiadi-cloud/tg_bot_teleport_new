from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.bot.keyboards.admin import admin_menu, back_to_admin_menu
from teleport_bot.bot.states import AdminStates
from teleport_bot.config.settings import Settings
from teleport_bot.models.db import Questionnaire, Subscription, User
from teleport_bot.models.enums import AdminAction
from teleport_bot.repositories.admin import AdminLogRepository, AdminRepository
from teleport_bot.repositories.settings import SettingsRepository
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.access import AccessService
from teleport_bot.services.questionnaire import QUESTIONS
from teleport_bot.services.telegram import TelegramService

router = Router()


def is_admin(settings: Settings, telegram_id: int) -> bool:
    return telegram_id in settings.admin_telegram_ids


def chat_type_value(chat_type: object) -> str:
    return chat_type.value if isinstance(chat_type, ChatType) else str(chat_type)


def render_chatid_response(chat_id: int, title: str | None, chat_type: object) -> str:
    chat_type_text = chat_type_value(chat_type)
    return f"ID этого чата:\n{chat_id}\n\nНазвание:\n{title or '—'}\n\nТип:\n{chat_type_text}"


async def deny(message: Message, session: AsyncSession, settings: Settings) -> None:
    admin_id = message.from_user.id if message.from_user else 0
    await AdminLogRepository(session).add(admin_id, AdminAction.ACCESS_DENIED)
    await message.answer("Недостаточно прав.")


async def guard_callback(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> bool:
    if is_admin(settings, callback.from_user.id):
        return True
    await AdminLogRepository(session).add(callback.from_user.id, AdminAction.ACCESS_DENIED)
    await callback.answer("Недостаточно прав.", show_alert=True)
    return False


@router.message(Command("admin"))
async def admin_command(message: Message, session: AsyncSession, settings: Settings) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    await message.answer("Административное меню", reply_markup=admin_menu())


@router.message(Command("chatid"))
async def chatid_command(message: Message, session: AsyncSession, settings: Settings) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return

    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эту команду нужно отправить внутри группы.")
        return

    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await message.answer(
            render_chatid_response(message.chat.id, message.chat.title, message.chat.type)
        )
        return

    await message.answer("Эту команду нужно отправить внутри группы.")


@router.callback_query(F.data == "admin:menu")
async def menu(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not await guard_callback(callback, session, settings):
        return
    await callback.message.answer("Административное меню", reply_markup=admin_menu())  # type: ignore[union-attr]
    await callback.answer()


def render_questionnaire(q: Questionnaire) -> str:
    user = q.user
    lines = [
        f"Telegram ID: {user.telegram_id}",
        f"username: @{user.username}" if user.username else "username: —",
        f"имя Telegram: {user.first_name} {user.last_name or ''}".strip(),
        f"дата заполнения: {q.completed_at or '—'}",
        "",
        "Ответы:",
    ]
    for question in QUESTIONS:
        lines.append(f"{question.text}\n{getattr(q, question.field) or '—'}")
    return "\n".join(lines)


@router.callback_query(F.data == "admin:new_questionnaires")
async def new_questionnaires(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    if not await guard_callback(callback, session, settings):
        return
    repo = AdminRepository(session)
    rows = await repo.new_questionnaires()
    if not rows:
        await callback.message.answer("Новых анкет нет.", reply_markup=back_to_admin_menu())  # type: ignore[union-attr]
    for q in rows:
        await callback.message.answer(render_questionnaire(q), reply_markup=back_to_admin_menu())  # type: ignore[union-attr]
        await repo.mark_questionnaire_viewed(q)
        await AdminLogRepository(session).add(
            callback.from_user.id, AdminAction.QUESTIONNAIRE_VIEWED, q.user.telegram_id
        )
    await callback.answer()


def render_user(user: User) -> str:
    sub = user.subscription.status if user.subscription else "inactive"
    return (
        f"Telegram ID: {user.telegram_id}\nusername: @{user.username if user.username else '—'}\n"
        f"имя: {user.first_name} {user.last_name or ''}\nдата регистрации: {user.created_at}\n"
        f"статус анкеты: {user.questionnaire.status if user.questionnaire else '—'}\n"
        f"статус подписки: {sub}\nпоследняя активность: {user.last_activity_at}"
    )


@router.callback_query(F.data.startswith("admin:users:"))
async def users(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not await guard_callback(callback, session, settings):
        return
    page = int(callback.data.rsplit(":", 1)[-1]) if callback.data else 1
    rows = await AdminRepository(session).users(page=page)
    text = "\n\n".join(render_user(u) for u in rows) or "Пользователи не найдены."
    await callback.message.answer(text, reply_markup=back_to_admin_menu())  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def stats(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not await guard_callback(callback, session, settings):
        return
    s = await AdminRepository(session).stats()
    await callback.message.answer(  # type: ignore[union-attr]
        "Статистика:\n"
        f"Всего пользователей: {s['total_users']}\nНовых сегодня: {s['new_today']}\n"
        f"Новых за неделю: {s['new_week']}\nЗаполненных анкет: {s['completed_questionnaires']}\n"
        f"Активных подписок: {s['active_subscriptions']}\n"
        f"Неактивных подписок: {s['inactive_subscriptions']}",
        reply_markup=back_to_admin_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:settings")
async def settings_view(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if not await guard_callback(callback, session, settings):
        return
    effective = await SettingsRepository(session).effective(settings)
    await callback.message.answer(  # type: ignore[union-attr]
        "Настройки:\n"
        f"Количество администраторов: {len(settings.admin_telegram_ids)}\n"
        f"ID закрытого Telegram-чата: {settings.private_chat_id or 'не настроено'}\n"
        f"Расписание круга: {effective['circle_schedule']}\n"
        f"Длительность подписки: {effective['subscription_duration_days']} дней\n"
        f"Ссылка на поддержку: {effective['support_url'] or 'не настроено'}\n"
        f"Стоимость подписки: {effective['subscription_price'] or 'не настроено'}\n\n"
        "Для изменения отправьте: /set_setting ключ значение",
        reply_markup=back_to_admin_menu(),
    )
    await callback.answer()


@router.message(Command("set_setting"))
async def set_setting_command(message: Message, session: AsyncSession, settings: Settings) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3:
        await message.answer(
            "Формат: /set_setting subscription_price|subscription_duration_days|"
            "circle_schedule|support_url значение"
        )
        return
    try:
        await SettingsRepository(session).set(parts[1], parts[2], message.from_user.id)
    except ValueError:
        await message.answer("Эту настройку нельзя изменить.")
        return
    await AdminLogRepository(session).add(
        message.from_user.id, AdminAction.SETTINGS_CHANGED, payload={"key": parts[1]}
    )
    await message.answer("Настройка изменена.", reply_markup=back_to_admin_menu())


@router.callback_query(F.data == "admin:activate_subscription")
async def activate_start(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, state: FSMContext
) -> None:
    if not await guard_callback(callback, session, settings):
        return
    await state.set_state(AdminStates.subscription_user_id)
    await callback.message.answer("Введите Telegram ID пользователя.")  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.subscription_user_id)
async def activate_user_id(
    message: Message, state: FSMContext, settings: Settings, session: AsyncSession
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    await state.update_data(target_user_id=int(message.text or "0"))
    await state.set_state(AdminStates.subscription_expires_at)
    await message.answer("Введите дату окончания подписки в формате YYYY-MM-DD.")


@router.message(AdminStates.subscription_expires_at)
async def activate_save(
    message: Message, state: FSMContext, settings: Settings, session: AsyncSession
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    data = await state.get_data()
    target_id = int(data["target_user_id"])
    user = await UserRepository(session).get_by_telegram_id(target_id)
    if user is None:
        await message.answer("Пользователь не найден.")
        await state.clear()
        return
    expires_at = datetime.fromisoformat(message.text or "").replace(tzinfo=UTC)
    await SubscriptionRepository(session).activate_manual(user, expires_at, message.from_user.id)
    await AdminLogRepository(session).add(
        message.from_user.id,
        AdminAction.MANUAL_SUBSCRIPTION_ACTIVATED,
        target_id,
        {"expires_at": expires_at.isoformat()},
    )
    await state.clear()
    await message.answer("Подписка активирована.", reply_markup=back_to_admin_menu())


@router.callback_query(F.data == "admin:send_link")
async def send_link_start(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, state: FSMContext
) -> None:
    if not await guard_callback(callback, session, settings):
        return
    await state.set_state(AdminStates.link_user_id)
    await callback.message.answer("Введите Telegram ID пользователя.")  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.link_user_id)
async def send_link(
    message: Message, session: AsyncSession, settings: Settings, state: FSMContext, bot: Bot
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    target_id = int(message.text or "0")
    chat_id = settings.private_chat_id
    if not chat_id:
        await message.answer("ID закрытого чата не настроен.")
        await state.clear()
        return
    try:
        result = await AccessService(session, TelegramService(bot)).send_manual_invite(
            message.from_user.id, target_id, chat_id
        )
    except ValueError:
        await message.answer("Пользователь не найден.")
    except PermissionError:
        await message.answer("Подписка неактивна.")
    except TelegramAPIError:
        await message.answer("Ошибка Telegram API.")
    else:
        if result.already_member:
            await message.answer("Пользователь уже состоит в закрытом чате.")
        else:
            await message.answer("Ссылка успешно отправлена.", reply_markup=back_to_admin_menu())
    finally:
        await state.clear()


def render_subscription(sub: Subscription) -> str:
    user = sub.user
    days = "—" if not sub.expires_at else (sub.expires_at.date() - datetime.now(UTC).date()).days
    return (
        f"Telegram ID: {user.telegram_id}\nusername: @{user.username if user.username else '—'}\n"
        f"имя: {user.first_name} {user.last_name or ''}\nстатус: {sub.status}\n"
        f"дата начала: {sub.started_at or '—'}\nдата окончания: {sub.expires_at or '—'}\n"
        f"дней осталось: {days}"
    )


@router.callback_query(F.data == "admin:subscriptions")
async def subscriptions_view(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    if not await guard_callback(callback, session, settings):
        return
    rows = await AdminRepository(session).subscriptions("active")
    text = "\n\n".join(render_subscription(s) for s in rows) or "Подписки не найдены."
    await callback.message.answer(text, reply_markup=back_to_admin_menu())  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "admin:import_subscription")
async def import_start(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, state: FSMContext
) -> None:
    if not await guard_callback(callback, session, settings):
        return
    await state.set_state(AdminStates.import_user_id)
    await callback.message.answer("Введите Telegram ID пользователя.")  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.import_user_id)
async def import_user_id(
    message: Message, state: FSMContext, settings: Settings, session: AsyncSession
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    await state.update_data(target_user_id=int(message.text or "0"))
    await state.set_state(AdminStates.import_expires_at)
    await message.answer("Введите дату окончания подписки в формате YYYY-MM-DD.")


@router.message(AdminStates.import_expires_at)
async def import_expires(
    message: Message, state: FSMContext, settings: Settings, session: AsyncSession
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    await state.update_data(expires_at=message.text or "")
    await state.set_state(AdminStates.import_comment)
    await message.answer("Введите комментарий или '-' если он не нужен.")


@router.message(AdminStates.import_comment)
async def import_save(
    message: Message, state: FSMContext, settings: Settings, session: AsyncSession
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    from teleport_bot.services.subscriptions import ManualSubscriptionService

    data = await state.get_data()
    expires_at = datetime.fromisoformat(data["expires_at"]).replace(tzinfo=UTC)
    comment = None if message.text == "-" else message.text
    await ManualSubscriptionService(session).import_subscription(
        int(data["target_user_id"]), expires_at, message.from_user.id, comment
    )
    await AdminLogRepository(session).add(
        message.from_user.id,
        AdminAction.SUBSCRIPTION_MIGRATED,
        int(data["target_user_id"]),
        {"expires_at": expires_at.isoformat(), "comment": comment},
    )
    await state.clear()
    await message.answer("Подписка импортирована.", reply_markup=back_to_admin_menu())


@router.callback_query(F.data == "admin:extend_subscription")
async def extend_start(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, state: FSMContext
) -> None:
    if not await guard_callback(callback, session, settings):
        return
    await state.set_state(AdminStates.extend_user_id)
    await callback.message.answer("Введите Telegram ID пользователя.")  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.extend_user_id)
async def extend_user_id(
    message: Message, state: FSMContext, settings: Settings, session: AsyncSession
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    await state.update_data(target_user_id=int(message.text or "0"))
    await state.set_state(AdminStates.extend_days)
    await message.answer("Введите количество дней.")


@router.message(AdminStates.extend_days)
async def extend_save(
    message: Message, state: FSMContext, settings: Settings, session: AsyncSession
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    from teleport_bot.services.subscriptions import ManualSubscriptionService

    data = await state.get_data()
    sub = await ManualSubscriptionService(session).extend_manual(
        int(data["target_user_id"]), int(message.text or "0"), message.from_user.id
    )
    await AdminLogRepository(session).add(
        message.from_user.id,
        AdminAction.SUBSCRIPTION_EXTENDED_MANUAL,
        int(data["target_user_id"]),
        {
            "days": int(message.text or "0"),
            "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
        },
    )
    await state.clear()
    await message.answer("Подписка продлена.", reply_markup=back_to_admin_menu())


@router.callback_query(F.data == "admin:cancel_subscription")
async def cancel_start(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, state: FSMContext
) -> None:
    if not await guard_callback(callback, session, settings):
        return
    await state.set_state(AdminStates.cancel_user_id)
    await callback.message.answer("Введите Telegram ID пользователя.")  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.cancel_user_id)
async def cancel_save(
    message: Message, state: FSMContext, settings: Settings, session: AsyncSession
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    from teleport_bot.services.subscriptions import ManualSubscriptionService

    target_id = int(message.text or "0")
    await ManualSubscriptionService(session).cancel(target_id, message.from_user.id)
    await AdminLogRepository(session).add(
        message.from_user.id, AdminAction.SUBSCRIPTION_CANCELLED, target_id
    )
    await state.clear()
    await message.answer("Подписка отменена.", reply_markup=back_to_admin_menu())


@router.callback_query(F.data == "admin:user_history")
async def history_start(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, state: FSMContext
) -> None:
    if not await guard_callback(callback, session, settings):
        return
    await state.set_state(AdminStates.history_user_id)
    await callback.message.answer("Введите Telegram ID пользователя.")  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.history_user_id)
async def history_show(
    message: Message, state: FSMContext, settings: Settings, session: AsyncSession
) -> None:
    if message.from_user is None or not is_admin(settings, message.from_user.id):
        await deny(message, session, settings)
        return
    target_id = int(message.text or "0")
    history = await AdminRepository(session).user_history(target_id)
    if history is None:
        await message.answer("Пользователь не найден.")
        await state.clear()
        return
    user = history["user"]
    questionnaire = history["questionnaire"]
    subscription = history["subscription"]
    payments = history["payments"]
    events = history["events"]
    admin_logs = history["admin_logs"]
    text = (
        f"История пользователя {target_id}\n"
        f"Анкета: {getattr(questionnaire, 'status', '—')}\n"
        f"Подписка: {getattr(subscription, 'status', '—')} до "
        f"{getattr(subscription, 'expires_at', '—')}\n"
        f"Платежи: {len(payments)}\n"
        f"События: {len(events)}\n"
        f"Административные действия: {len(admin_logs)}\n"
        f"Telegram username: @{user.username if user.username else '—'}"
    )
    await state.clear()
    await message.answer(text, reply_markup=back_to_admin_menu())
