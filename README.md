# Телепорт Telegram Bot

Production-ready Telegram-бот «Телепорт» на Python 3.12, aiogram 3, PostgreSQL, SQLAlchemy Async, Alembic и aiohttp.

## Возможности

- `/start`, onboarding, анкета пользователя, восстановление прогресса.
- Административное меню `/admin`: просмотр анкет и пользователей, статистика, ручная активация подписки и ручная выдача ссылки.
- YooKassa: создание платежа, переиспользование свежего pending-платежа, ручная проверка оплаты и webhook `/webhooks/yookassa`.
- Автоматическая активация или продление подписки после подтверждения платежа.
- Подготовленная модель сохранённых платёжных методов для будущих рекуррентных платежей.
- Health endpoint: `GET /health`.

## Настройка окружения

```bash
cp .env.example .env
```

Обязательные переменные:

- `BOT_TOKEN` — токен Telegram-бота.
- `DATABASE_URL` — PostgreSQL DSN для SQLAlchemy asyncpg.
- `ADMIN_IDS` — Telegram ID администраторов через запятую.
- `PRIVATE_CHAT_ID` — ID закрытого Telegram-чата.
- `PUBLIC_BASE_URL` или `WEBHOOK_HOST` — публичный адрес сервиса за reverse proxy.
- `YOOKASSA_SHOP_ID` и `YOOKASSA_SECRET_KEY` — данные магазина YooKassa, секреты не коммитить.
- `YOOKASSA_RETURN_URL` — URL возврата после оплаты.
- `YOOKASSA_WEBHOOK_PATH` — путь webhook, по умолчанию `/webhooks/yookassa`.
- `YOOKASSA_CURRENCY`, `SUBSCRIPTION_PRICE`, `SUBSCRIPTION_DURATION_DAYS` — валюта, цена и срок подписки.
- `PAYMENT_PENDING_TTL_MINUTES`, `PAYMENT_REUSE_MINUTES` — устаревание и переиспользование pending-платежей.
- `PAYMENT_SAVE_METHOD_ENABLED` — запрашивать ли сохранение метода оплаты.

Цена обрабатывается как `Decimal`, не `float`.

## YooKassa

В личном кабинете YooKassa настройте webhook на публичный URL:

```text
https://<PUBLIC_BASE_URL><YOOKASSA_WEBHOOK_PATH>
```

Поддерживаемые события:

- `payment.succeeded`
- `payment.canceled`
- `payment.waiting_for_capture`

Webhook не полагается только на входящий JSON: сервис повторно получает платёж через YooKassa API, сверяет ID платежа, сумму, валюту и metadata (`user_id`, `telegram_id`, `product`). При неоднозначности подписка не активируется.

## Тестовый режим YooKassa

Для тестового платежа используйте тестовый магазин YooKassa, тестовые `SHOP_ID`/`SECRET_KEY`, публичный HTTPS URL webhook и кнопку «💳 ОПЛАТИТЬ» в боте. После оплаты можно нажать «🔄 ПРОВЕРИТЬ ОПЛАТУ» — ручная проверка использует тот же обработчик статусов, что и webhook.

Если оплата прошла, но ссылка не пришла: подписка остаётся активной, ошибка выдачи доступа пишется в EventLog, администраторы уведомляются, пользователь может запросить ссылку повторно через существующий сценарий выдачи.

## Сохранение платёжного метода

Если `PAYMENT_SAVE_METHOD_ENABLED=true`, при первой оплате YooKassa получает запрос на сохранение метода. После успешной оплаты бот сохраняет только безопасный идентификатор метода и маскированное описание. Полный номер карты, CVV, токены и секретный ключ YooKassa не сохраняются.

> Рекуррентные списания пока не включены: scheduler и автоматические списания не реализованы. Добавлен только интерфейс `RecurringPaymentService` для будущего этапа.

## Запуск

```bash
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
docker compose build
docker compose up -d postgres
alembic upgrade head
```

## Структура

```text
src/teleport_bot/
  bot/              # aiogram app, handlers, FSM, keyboards, middlewares
  config/           # settings and structured logging
  db/               # SQLAlchemy base/session infrastructure
  models/           # ORM models and enums
  repositories/     # database access layer
  services/         # payments, access, Telegram and admin notifications
  texts/            # user-facing content
  web/              # health and YooKassa webhook endpoints
alembic/            # database migrations
tests/              # unit and async repository tests
```

## Что намеренно не реализовано

Автоматические рекуррентные списания, scheduler автоплатежей, напоминания о продлении, автоматическое удаление пользователя из чата, импорт старых пользователей и дополнительные веб-интерфейсы.


## Подписки, напоминания и администрирование

- Ежедневный APScheduler job проверяет активные и ручные подписки, отправляет напоминания за 3 дня, за 1 день и в день окончания, а также переводит просроченные подписки в `expired`.
- Повторная успешная оплата через существующий `PaymentService` продлевает текущую запись `Subscription`, не создавая дубль.
- В админке доступны импорт мигрированных подписок, просмотр подписок, ручное продление, отмена, история пользователя и изменение настроек.
- Настройки `subscription_price`, `subscription_duration_days`, `circle_schedule`, `support_url` хранятся в таблице `app_settings`; если значения нет, используется `.env`.
