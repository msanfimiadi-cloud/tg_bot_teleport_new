from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.bot.keyboards.onboarding import (
    back_keyboard,
    confirm_questionnaire,
    confirm_restart,
    edit_questions,
    one_button,
    start_choice,
)
from teleport_bot.bot.states import OnboardingStates
from teleport_bot.config.settings import Settings
from teleport_bot.models.db import User
from teleport_bot.models.enums import EventType, FunnelStatus, OnboardingStatus, QuestionnaireStatus
from teleport_bot.repositories.events import EventRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.admin_notifications import AdminNotifier
from teleport_bot.services.questionnaire import (
    QUESTIONS,
    ValidationError,
    complete,
    get_question,
    progress_text,
    render_summary,
    set_answer,
    validate_answer,
)
from teleport_bot.texts import content

router = Router()


async def get_current_user(session: AsyncSession, message: Message) -> tuple[User, bool]:
    if message.from_user is None:
        raise RuntimeError("message without from_user")
    return await UserRepository(session).upsert_from_telegram(message.from_user)


async def ask_question(message: Message, user: User, state: FSMContext) -> None:
    qn = user.questionnaire
    step = max(1, min(qn.current_step or 1, len(QUESTIONS)))
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
        await message.answer("Ты уже начал анкету.", reply_markup=start_choice())
    else:
        await message.answer(
            content.WELCOME, reply_markup=one_button("ДАЛЬШЕ", "onboarding:welcome_next")
        )


@router.callback_query(F.data == "onboarding:welcome_next")
async def welcome_next(callback: CallbackQuery) -> None:
    await callback.message.answer(
        content.HOW_IT_WORKS, reply_markup=one_button("ДАЛЬШЕ", "questionnaire:start")
    )  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "questionnaire:start")
async def questionnaire_start(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user is None or callback.message is None:
        await callback.answer()
        return
    user.questionnaire.status = QuestionnaireStatus.IN_PROGRESS.value
    user.questionnaire.current_step = 1
    user.onboarding_status = OnboardingStatus.QUESTIONNAIRE.value
    await EventRepository(session).add(EventType.QUESTIONNAIRE_STARTED, user)
    await ask_question(callback.message, user, state)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:continue")
async def questionnaire_continue(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and callback.message:
        await ask_question(callback.message, user, state)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:restart_ask")
async def restart_ask(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Старые ответы будут заменены. Начать заново?", reply_markup=confirm_restart()
    )  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "questionnaire:restart_confirm")
async def restart_confirm(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and callback.message:
        qn = user.questionnaire
        for question in QUESTIONS:
            setattr(qn, question.field, None)
        qn.status = QuestionnaireStatus.IN_PROGRESS.value
        qn.current_step = 1
        qn.completed_at = None
        await EventRepository(session).add(EventType.QUESTIONNAIRE_RESTARTED, user)
        await ask_question(callback.message, user, state)
    await callback.answer()


@router.message(OnboardingStates.answering)
async def answer_question(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user, _ = await get_current_user(session, message)
    data = await state.get_data()
    step = int(data.get("step", user.questionnaire.current_step or 1))
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


@router.callback_query(F.data == "questionnaire:back")
async def back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    data = await state.get_data()
    step = max(1, int(data.get("step", user.questionnaire.current_step if user else 1)) - 1)
    if user and callback.message:
        user.questionnaire.current_step = step
        await state.update_data(step=step)
        await ask_question(callback.message, user, state)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:edit")
async def edit(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Какой ответ изменить?", reply_markup=edit_questions(len(QUESTIONS))
    )  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.startswith("questionnaire:edit:"))
async def edit_specific(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    step = int(callback.data.rsplit(":", 1)[-1]) if callback.data else 1
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and callback.message:
        user.questionnaire.current_step = step
        await state.update_data(step=step)
        await ask_question(callback.message, user, state)
    await callback.answer()


@router.callback_query(F.data == "questionnaire:confirm")
async def confirm(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, settings: Settings
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and callback.message:
        changed = complete(user, user.questionnaire)
        if changed:
            events = EventRepository(session)
            await events.add(EventType.QUESTIONNAIRE_COMPLETED, user)
            await AdminNotifier(bot, settings.admin_telegram_ids, events).questionnaire_completed(
                user, user.questionnaire
            )
        await callback.message.answer(
            content.CIRCLE_TEMPLATE.format(circle_schedule=settings.circle_schedule),
            reply_markup=one_button("ДАЛЬШЕ", "onboarding:final"),
        )
    await callback.answer()


@router.callback_query(F.data == "onboarding:circle")
async def circle(callback: CallbackQuery, settings: Settings) -> None:
    await callback.message.answer(
        content.CIRCLE_TEMPLATE.format(circle_schedule=settings.circle_schedule),
        reply_markup=one_button("ДАЛЬШЕ", "onboarding:final"),
    )  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "onboarding:final")
async def final_info(callback: CallbackQuery) -> None:
    await callback.message.answer(
        content.FINAL_INFO, reply_markup=one_button("ГОТОВ НАЧАТЬ", "payment:stub")
    )  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "payment:stub")
async def payment_stub(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, settings: Settings
) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and callback.message:
        user.funnel_status = FunnelStatus.PAYMENT_STAGE_REACHED.value
        user.onboarding_status = OnboardingStatus.PAYMENT_STAGE.value
        events = EventRepository(session)
        await events.add(EventType.PAYMENT_STAGE_REACHED, user)
        await AdminNotifier(bot, settings.admin_telegram_ids, events).payment_stage_reached(user)
        await callback.message.answer(content.PAYMENT_STUB)
    await callback.answer()
