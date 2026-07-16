from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu() -> InlineKeyboardMarkup:
    buttons = [
        ("📋 Новые анкеты", "admin:new_questionnaires"),
        ("👥 Пользователи", "admin:users:1"),
        ("💳 Подписки", "admin:subscriptions"),
        ("📨 Отправить ссылку", "admin:send_link"),
        ("➕ Активировать подписку", "admin:activate_subscription"),
        ("⬇️ Импорт подписки", "admin:import_subscription"),
        ("➕ Продлить подписку", "admin:extend_subscription"),
        ("🚫 Отменить подписку", "admin:cancel_subscription"),
        ("🕘 История пользователя", "admin:user_history"),
        ("📊 Статистика", "admin:stats"),
        ("🤝 Партнёры", "admin:partners"),
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


def partners_menu() -> InlineKeyboardMarkup:
    buttons = [
        ("Список партнёров", "admin:partners:list"),
        ("Добавить партнёра", "admin:partners:add"),
        ("Статистика партнёров", "admin:partners:stats:all"),
        ("Найти партнёра", "admin:partners:find"),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d)] for t, d in buttons]
        + [[InlineKeyboardButton(text="⬅️ В меню", callback_data="admin:menu")]]
    )
