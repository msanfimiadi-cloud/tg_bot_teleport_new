from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.bot.keyboards.onboarding import (
    active_subscription_keyboard,
    back_keyboard,
    confirm_questionnaire,
    confirm_restart,
    edit_questions,
    one_button,
    payment_keyboard,
    request_email_keyboard,
)
from teleport_bot.bot.states import OnboardingStates
from teleport_bot.config.settings import Settings
from teleport_bot.models.db import User
from teleport_bot.models.enums import EventType, FunnelStatus, OnboardingStatus, QuestionnaireStatus
from teleport_bot.repositories.events import EventRepository
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.admin_notifications import AdminNotifier
from teleport_bot.services.payments import (
    PaymentError,
    PaymentService,
    normalize_email,
)
from teleport_bot.services.public_welcome import publish_questionnaire_and_send_welcome
from teleport_bot.services.questionnaire import (
    QUESTIONS,
    ValidationError,
    complete,
    get_question,
    progress_text,
    render_summary,
    restore_progress,
    set_answer,
    validate_answer,
)
from teleport_bot.services.referrals import ReferralService
from teleport_bot.services.yookassa import YooKassaGateway, YooKassaRequestError
from teleport_bot.texts import content

router = Router()


def callback_message(callback: CallbackQuery) -> Message | None:
    return callback.message if isinstance(callback.message, Message) else None


async def get_current_user(session: AsyncSession, message: Message) -> tuple[User, bool]:
    if message.from_user is None:
        raise RuntimeError("message without from_user")
    return await UserRepository(session).upsert_from_telegram(message.from_user)


async def ask_question(
    message: Message, user: User, state: FSMContext, *, restore_from_db: bool = True
) -> None:
    qn = user.questionnaire
    if restore_from_db:
        step = restore_progress(qn)
    else:
        step = max(1, min(qn.current_step or 1, len(QUESTIONS)))
        qn.status = QuestionnaireStatus.IN_PROGRESS.value
    await state.set_state(OnboardingStates.answering)
    await state.update_data(step=step)
    question = get_question(step)
    old = getattr(qn, question.field) or ""
    suffix = f"\n\nРанее: {old}" if old else ""
    await message.answer(
        f"{progress_text(step)}\n\n{question.text}{suffix}", reply_markup=back_keyboard()
    )


@router.message(CommandStart())
async def start(
    message: Message, session: AsyncSession, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    user, created = await get_current_user(session, message)
    start_parts = (message.text or "").split(maxsplit=1)
    ref_payload = start_parts[1] if len(start_parts) > 1 else None
    referrals = ReferralService(session)
    await referrals.link_partner_user(user)
    await referrals.attribute_start(user, ref_payload, existing_user=not created)
    events = EventRepository(session)
    if created:
        await events.add(EventType.USER_STARTED, user)
        await AdminNotifier(bot, settings.admin_telegram_ids, events).user_started(user)
        user.onboarding_status = OnboardingStatus.INFO_STARTED.value
        await message.answer(
            content.WELCOME, reply_markup=one_button("ДАЛЬШЕ", "onboarding:welcome_next")
        )
        return
    qn = user.questionnaire
    if qn.status == QuestionnaireStatus.COMPLETED.value:
        await message.answer(
            "Анкета уже сохранена. Можно перейти к следующему этапу.",
            reply_markup=one_button("ДАЛЬШЕ", "onboarding:circle"),
        )
    elif qn.status == QuestionnaireStatus.IN_PROGRESS.value:
        await message.answer("Восстанавливаю анкету с последнего незавершённого вопроса.")
        await ask_question(message, user, state)
    else:
        await message.answer(
            content.WELCOME, reply_markup=one_button("ДАЛЬШЕ", "onboarding:welcome_next")
        )


@router.callback_query(F.data == "onboarding:welcome_next")
async def welcome_next(callback: CallbackQuery) -> None:
    if message := callback_message(callback):
        await message.answer(
            content.HOW_IT_WORKS, reply_markup=one_button("ДАЛЬШЕ", "questionnaire:start")
        )
    await callback.answer()


@router.callback_query(F.data == "questionnaire:start")
async def questionnaire_start(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    message = callback_message(callback)
    if user is None or message is None:
        await callback.answer()
        return
    user.questionnaire.status = QuestionnaireStatus.IN_PROGRESS.value
    user.questionnaire.current_step = 1
    user.onboarding_status = OnboardingStatus.QUESTIONNAIRE.value
    await EventRepository(session).add(EventType.QUESTIONNAIRE_STARTED, user)
    await ask_question(message, user, state)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:continue")
async def questionnaire_continue(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and (message := callback_message(callback)):
        await ask_question(message, user, state)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:restart_ask")
async def restart_ask(callback: CallbackQuery) -> None:
    if message := callback_message(callback):
        await message.answer(
            "Старые ответы будут заменены. Начать заново?", reply_markup=confirm_restart()
        )
    await callback.answer()


@router.callback_query(F.data == "questionnaire:restart_confirm")
async def restart_confirm(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and (message := callback_message(callback)):
        qn = user.questionnaire
        for question in QUESTIONS:
            setattr(qn, question.field, None)
        qn.status = QuestionnaireStatus.IN_PROGRESS.value
        qn.current_step = 1
        qn.completed_at = None
        await EventRepository(session).add(EventType.QUESTIONNAIRE_RESTARTED, user)
        await ask_question(message, user, state)
    await callback.answer()


async def _save_questionnaire_answer(
    message: Message, session: AsyncSession, state: FSMContext, *, restore_from_db: bool = False
) -> None:
    user, _ = await get_current_user(session, message)
    data = await state.get_data()
    step = (
        restore_progress(user.questionnaire)
        if restore_from_db
        else int(data.get("step", user.questionnaire.current_step or 1))
    )
    await state.set_state(OnboardingStates.answering)
    await state.update_data(step=step)
    question = get_question(step)
    try:
        answer = validate_answer(question, message.text or "")
    except ValidationError as exc:
        await message.answer(str(exc), reply_markup=back_keyboard())
        return
    set_answer(user.questionnaire, step, answer)
    await EventRepository(session).add(EventType.QUESTIONNAIRE_STEP_COMPLETED, user, {"step": step})
    if step == len(QUESTIONS):
        await state.clear()
        await message.answer(
            f"{content.QUESTIONNAIRE_CONFIRM_PREFIX}\n\n{render_summary(user.questionnaire)}",
            reply_markup=confirm_questionnaire(),
        )
    else:
        await state.update_data(step=step + 1)
        await ask_question(message, user, state)


@router.message(OnboardingStates.answering)
async def answer_question(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await _save_questionnaire_answer(message, session, state)


@router.message(F.text)
async def recover_questionnaire_answer(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if await state.get_state() is not None:
        return
    user, _ = await get_current_user(session, message)
    if user.questionnaire.status != QuestionnaireStatus.IN_PROGRESS.value:
        return
    await _save_questionnaire_answer(message, session, state, restore_from_db=True)


@router.callback_query(F.data == "questionnaire:back")
async def back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    data = await state.get_data()
    step = max(1, int(data.get("step", user.questionnaire.current_step if user else 1)) - 1)
    if user and (message := callback_message(callback)):
        user.questionnaire.current_step = step
        await state.set_state(OnboardingStates.answering)
        await state.update_data(step=step)
        await ask_question(message, user, state, restore_from_db=False)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:edit")
async def edit(callback: CallbackQuery) -> None:
    if message := callback_message(callback):
        await message.answer("Какой ответ изменить?", reply_markup=edit_questions(len(QUESTIONS)))
    await callback.answer()


@router.callback_query(F.data.startswith("questionnaire:edit:"))
async def edit_specific(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    step = int(callback.data.rsplit(":", 1)[-1]) if callback.data else 1
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and (message := callback_message(callback)):
        user.questionnaire.current_step = step
        await state.set_state(OnboardingStates.answering)
        await state.update_data(step=step)
        await ask_question(message, user, state, restore_from_db=False)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:confirm")
async def confirm(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, settings: Settings
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and (message := callback_message(callback)):
        changed = complete(user, user.questionnaire)
        if changed:
            events = EventRepository(session)
            await events.add(EventType.QUESTIONNAIRE_COMPLETED, user)
            await ReferralService(session).mark_questionnaire_completed(user)
            await AdminNotifier(bot, settings.admin_telegram_ids, events).questionnaire_completed(
                user, user.questionnaire
            )
        await message.answer(
            content.CIRCLE_TEMPLATE.format(circle_schedule=settings.circle_schedule),
            reply_markup=one_button("ДАЛЬШЕ", "onboarding:final"),
        )
    await callback.answer()


def _is_private_chat_join(event: ChatMemberUpdated, private_chat_id: int | str | None) -> bool:
    if private_chat_id is None or str(event.chat.id) != str(private_chat_id):
        return False
    new_status = getattr(event.new_chat_member.status, "value", event.new_chat_member.status)
    old_status = getattr(event.old_chat_member.status, "value", event.old_chat_member.status)
    active_statuses = {"member", "administrator", "creator"}
    return str(new_status) in active_statuses and str(old_status) not in active_statuses


@router.chat_member()
async def private_chat_member_updated(
    event: ChatMemberUpdated, session: AsyncSession, bot: Bot, settings: Settings
) -> None:
    if not _is_private_chat_join(event, settings.private_chat_id):
        return
    user = await UserRepository(session).get_by_telegram_id(event.new_chat_member.user.id)
    if user is None:
        return
    await publish_questionnaire_and_send_welcome(
        bot, settings, EventRepository(session), user, user.questionnaire
    )


@router.callback_query(F.data == "onboarding:circle")
async def circle(callback: CallbackQuery, settings: Settings) -> None:
    if message := callback_message(callback):
        await message.answer(
            content.CIRCLE_TEMPLATE.format(circle_schedule=settings.circle_schedule),
            reply_markup=one_button("ДАЛЬШЕ", "onboarding:final"),
        )
    await callback.answer()


@router.callback_query(F.data == "onboarding:final")
async def final_info(callback: CallbackQuery) -> None:
    if message := callback_message(callback):
        await message.answer(
            content.FINAL_INFO, reply_markup=one_button("ГОТОВ НАЧАТЬ", "payment:start")
        )
    await callback.answer()


@router.callback_query(F.data.in_({"payment:start", "payment:renew", "payment:email_continue"}))
async def payment_start(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and (message := callback_message(callback)):
        user.funnel_status = FunnelStatus.PAYMENT_STAGE_REACHED.value
        user.onboarding_status = OnboardingStatus.PAYMENT_STAGE.value
        events = EventRepository(session)
        await events.add(EventType.PAYMENT_STAGE_REACHED, user)
        await AdminNotifier(bot, settings.admin_telegram_ids, events).payment_stage_reached(user)
        subscription = user.subscription
        if (
            callback.data == "payment:start"
            and SubscriptionRepository.is_active(subscription)
            and subscription is not None
            and subscription.expires_at is not None
        ):
            await message.answer(
                f"Подписка активна до: {subscription.expires_at:%d.%m.%Y}",
                reply_markup=active_subscription_keyboard(),
            )
        else:
            if not user.email:
                await state.set_state(OnboardingStates.payment_email)
                await message.answer(
                    "Для фискального чека нужен email. "
                    "Укажи email, и я сразу продолжу создание платежа.",
                    reply_markup=request_email_keyboard(),
                )
                await callback.answer()
                return
            try:
                payment = await PaymentService(
                    session, settings, YooKassaGateway(settings)
                ).create_or_reuse_payment(callback.from_user.id)
                await ReferralService(session).mark_payment_link_created(user)
            except YooKassaRequestError as exc:
                await AdminNotifier(
                    bot, settings.admin_telegram_ids, events
                ).payment_creation_failed(
                    user,
                    status=exc.status,
                    error_code=exc.error_code,
                    parameter=exc.parameter,
                )
                await message.answer(
                    "Не удалось создать платёж. Попробуй ещё раз немного позже. "
                    "Если ошибка повторится — напиши в поддержку."
                )
            except PaymentError as exc:
                await message.answer(f"Не удалось создать оплату: {exc}")
            else:
                await message.answer(
                    "Для доступа в закрытое пространство необходимо оплатить подписку.\n\n"
                    f"Стоимость: {payment.amount} {payment.currency}\n"
                    f"Срок: {settings.subscription_duration_days} дней\n"
                    f"{settings.subscription_description}",
                    reply_markup=payment_keyboard(
                        payment.confirmation_url or settings.yookassa_return_url
                    ),
                )
    await callback.answer()


@router.message(OnboardingStates.payment_email)
async def payment_email(
    message: Message, session: AsyncSession, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    user, _ = await get_current_user(session, message)
    try:
        email = normalize_email(message.text or "")
    except PaymentError:
        await message.answer(
            "Похоже, email указан неверно. Проверь адрес и отправь его ещё раз.",
            reply_markup=request_email_keyboard(),
        )
        return
    await UserRepository(session).set_email(user, email)
    await state.clear()
    events = EventRepository(session)
    try:
        payment = await PaymentService(
            session, settings, YooKassaGateway(settings)
        ).create_or_reuse_payment(user.telegram_id)
        await ReferralService(session).mark_payment_link_created(user)
    except YooKassaRequestError as exc:
        await AdminNotifier(bot, settings.admin_telegram_ids, events).payment_creation_failed(
            user, status=exc.status, error_code=exc.error_code, parameter=exc.parameter
        )
        await message.answer(
            "Email сохранён, но не удалось создать платёж. Попробуй ещё раз немного позже."
        )
    except PaymentError as exc:
        await message.answer(f"Email сохранён, но не удалось создать оплату: {exc}")
    else:
        await message.answer(
            "Email сохранён. Для доступа в закрытое пространство необходимо оплатить подписку.\n\n"
            f"Стоимость: {payment.amount} {payment.currency}\n"
            f"Срок: {settings.subscription_duration_days} дней\n"
            f"{settings.subscription_description}",
            reply_markup=payment_keyboard(payment.confirmation_url or settings.yookassa_return_url),
        )


@router.callback_query(F.data == "payment:check")
async def payment_check(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if message := callback_message(callback):
        try:
            payment = await PaymentService(
                session, settings, YooKassaGateway(settings)
            ).check_latest_payment(callback.from_user.id)
        except Exception as exc:
            await message.answer(
                f"Оплата пока не подтверждена или недоступна проверка: {exc.__class__.__name__}"
            )
        else:
            if payment is None:
                await message.answer("Актуальный платёж не найден. Создай новую оплату.")
            elif payment.status == "succeeded":
                await message.answer(
                    "Оплата подтверждена. Подписка активирована, доступ будет выдан автоматически."
                )
            elif payment.status == "canceled":
                await message.answer("Платёж отменён. Можно создать новую оплату.")
            else:
                await message.answer("Оплата пока не подтверждена.")
    await callback.answer()


@router.callback_query(F.data == "payment:get_invite")
async def payment_get_invite(callback: CallbackQuery) -> None:
    if message := callback_message(callback):
        await message.answer(
            "Запрос ссылки доступен через администраторскую выдачу или после подтверждения оплаты."
        )
    await callback.answer()
