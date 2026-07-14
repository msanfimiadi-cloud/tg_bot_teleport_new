# Телепорт Telegram Bot

Новый production-ready каркас Telegram-бота «Телепорт» на Python 3.12, aiogram 3, PostgreSQL, SQLAlchemy Async и Alembic.

## Возможности текущего этапа

- `/start` с приветственными экранами и inline-навигацией.
- Анкета из 5 вопросов с валидацией, прогрессом, кнопкой «НАЗАД» и изменением ответов.
- Сохранение пользователя, анкеты, прогресса и событий в БД.
- Восстановление незавершённой анкеты после перезапуска бота.
- Безопасная заглушка будущего платёжного этапа.
- Уведомления администраторам по числовым Telegram ID из `ADMIN_IDS`.
- Health endpoint: `GET /health`.

## Запуск локально

```bash
cp .env.example .env
# Заполните BOT_TOKEN и ADMIN_IDS в .env
docker compose up --build
```

Миграции применяются автоматически в контейнере бота. Вручную:

```bash
alembic upgrade head
```

## Проверки

```bash
pytest
ruff check .
mypy src tests
```

## Структура

```text
src/teleport_bot/
  bot/              # aiogram app, handlers, FSM, keyboards, middlewares
  config/           # settings and structured logging
  db/               # SQLAlchemy base/session infrastructure
  models/           # ORM models and enums
  repositories/     # database access layer
  services/         # business logic and admin notifications
  texts/            # user-facing content
  web/              # health endpoint
alembic/            # database migrations
tests/              # unit and async repository tests
```

## Что намеренно не реализовано

YooKassa, реальные платежи, рекуррентные списания, выдача ссылок в закрытый чат, подписки, VK, розыгрыши, Excel-экспорт, веб-интерфейс и полноценная админ-панель.
