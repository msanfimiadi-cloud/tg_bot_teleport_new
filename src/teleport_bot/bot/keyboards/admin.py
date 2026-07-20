from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu() -> InlineKeyboardMarkup:
    buttons = [
        ("📋 Новые анкеты", "admin:new_questionnaires"),
        ("👥 Пользователи", "admin:users:1"),
        ("💳 Подписки", "admin:subscriptions"),
        ("💰 Напомнить об оплате", "admin:payment_reminder"),
        ("📨 Ссылка в закрытый чат", "admin:send_link"),
        ("➕ Активировать подписку", "admin:activate_subscription"),
        ("⬇️ Импорт подписки", "admin:import_subscription"),
        ("➕ Продлить подписку", "admin:extend_subscription"),
        ("🚫 Отменить подписку", "admin:cancel_subscription"),
        ("🕘 История пользователя", "admin:user_history"),
        ("📊 Статистика", "admin:stats"),
        ("🤝 Партнёры", "admin:partners"),
        ("✍️ Написать сообщение в чат", "admin:chat_message:start"),
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


def payment_reminder_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📣 Отправить всем",
                    callback_data="admin:payment_reminder:all",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Отправить одному",
                    callback_data="admin:payment_reminder:user",
                )
            ],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="admin:menu")],
        ]
    )


def payment_reminder_confirm(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Да, отправить ({count})",
                    callback_data="admin:payment_reminder:confirm_all",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="admin:payment_reminder",
                )
            ],
        ]
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


def admin_chat_message_start_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:chat_message:cancel")],
            [InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="admin:menu")],
        ]
    )


def admin_chat_message_preview_menu(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать", callback_data=f"admin:chat_message:publish:{draft_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить текст", callback_data=f"admin:chat_message:edit:{draft_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=f"admin:chat_message:cancel:{draft_id}"
                )
            ],
        ]
    )


def admin_chat_message_retry_menu(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Повторить", callback_data=f"admin:chat_message:publish:{draft_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить", callback_data=f"admin:chat_message:edit:{draft_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=f"admin:chat_message:cancel:{draft_id}"
                )
            ],
        ]
    )
