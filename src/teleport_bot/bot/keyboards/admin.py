from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu() -> InlineKeyboardMarkup:
    buttons = [
        ("📋 Новые анкеты", "admin:new_questionnaires"),
        ("👥 Пользователи", "admin:users:1"),
        ("💳 Подписки", "admin:subscriptions"),
        ("📨 Отправить ссылку", "admin:send_link"),
        ("➕ Активировать подписку", "admin:activate_subscription"),
        ("📊 Статистика", "admin:stats"),
        ("⚙️ Настройки", "admin:settings"),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data)] for text, data in buttons
        ]
    )


def back_to_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="admin:menu")]]
    )
