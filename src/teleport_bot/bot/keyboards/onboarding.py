from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def one_button(text: str, callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback_data)]]
    )


def start_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Продолжить анкету", callback_data="questionnaire:continue"
                )
            ],
            [InlineKeyboardButton(text="Начать заново", callback_data="questionnaire:restart_ask")],
        ]
    )


def confirm_restart() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, начать заново", callback_data="questionnaire:restart_confirm"
                )
            ],
            [InlineKeyboardButton(text="Нет, продолжить", callback_data="questionnaire:continue")],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return one_button("НАЗАД", "questionnaire:back")


def confirm_questionnaire() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ВСЁ ВЕРНО", callback_data="questionnaire:confirm")],
            [InlineKeyboardButton(text="ИЗМЕНИТЬ ОТВЕТЫ", callback_data="questionnaire:edit")],
        ]
    )


def edit_questions(total: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Вопрос {i}", callback_data=f"questionnaire:edit:{i}")]
            for i in range(1, total + 1)
        ]
    )


def payment_keyboard(confirmation_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 ОПЛАТИТЬ", url=confirmation_url)],
            [InlineKeyboardButton(text="🔄 ПРОВЕРИТЬ ОПЛАТУ", callback_data="payment:check")],
            [InlineKeyboardButton(text="⬅️ НАЗАД", callback_data="onboarding:final")],
        ]
    )


def active_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Получить ссылку в чат", callback_data="payment:get_invite"
                )
            ],
            [InlineKeyboardButton(text="Продлить подписку", callback_data="payment:renew")],
        ]
    )
