# Телепорт Telegram Bot

Production-ready Telegram-бот «Телепорт» для onboarding, анкеты, оплат YooKassa, подписок, административного управления и фоновых задач. Стек: Python 3.12, aiogram 3, aiohttp, SQLAlchemy 2 Async, PostgreSQL, Alembic, APScheduler, structlog.

## Архитектура

```mermaid
flowchart LR
    U[Пользователь Telegram] --> TG[Telegram Bot API]
    TG --> B[aiogram bot handlers]
    B --> FSM[FSM состояния]
    B --> S[Services]
    S --> R[Repositories]
    R --> DB[(PostgreSQL)]
    S --> YK[YooKassa API]
    YK --> WH[aiohttp webhook]
    WH --> S
    SCH[APScheduler] --> S
    ADM[Администратор Telegram] --> B
```

Основные слои:

- `bot/` — aiogram-приложение, handlers, keyboards, FSM и middleware с транзакционной сессией.
- `services/` — бизнес-операции: анкета, платежи, подписки, доступ в закрытый чат, уведомления.
- `repositories/` — единственный слой прямого доступа к БД.
- `models/` — SQLAlchemy ORM-модели и enum-значения.
- `web/` — health endpoint и webhook YooKassa.
- `scheduler.py` — ежедневные фоновые проверки подписок.
- `alembic/` — миграции PostgreSQL.

## Структура проекта

```text
src/teleport_bot/
  bot/              # aiogram app, handlers, FSM states, keyboards, middlewares
  config/           # pydantic settings, logging
  db/               # Base, timestamp mixin, async session factory
  models/           # ORM models and enums
  repositories/     # typed database access layer
  services/         # questionnaire, payments, yookassa, subscriptions, access
  texts/            # user-facing copy
  web/              # health server and payment webhook
alembic/            # Alembic environment and versions
tests/              # onboarding, admin, repositories, subscriptions tests
```

## База данных

Ключевые таблицы:

- `users` — Telegram-профиль, статусы onboarding/funnel, даты активности.
- `questionnaires` — ответы анкеты, текущий шаг FSM, статус и review-дата.
- `payments` — YooKassa-платежи с idempotency key, статусами, суммой, безопасной metadata и индексами для поиска.
- `payment_methods` — только безопасный provider method id и маскированное описание, без карточных данных.
- `subscriptions` — единая подписка пользователя, статус, срок, источник активации и последний платёж.
- `subscription_reminders` — защита от повторных напоминаний одного типа.
- `app_settings` — runtime-настройки админки.
- `admin_action_logs` и `event_logs` — аудит действий и событий без секретов.

## Настройка окружения

```bash
cp .env.example .env
```

Обязательные переменные:

- `BOT_TOKEN` — токен Telegram-бота.
- `DATABASE_URL` — async SQLAlchemy DSN, например `postgresql+asyncpg://teleport:teleport@postgres:5432/teleport`.
- `ADMIN_IDS` — Telegram ID администраторов через запятую.
- `PRIVATE_CHAT_ID` — ID закрытого Telegram-чата.
- `PUBLIC_BASE_URL` / `WEBHOOK_HOST` — публичный HTTPS-адрес сервиса.
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_RETURN_URL`, `YOOKASSA_WEBHOOK_PATH`.
- `SUBSCRIPTION_PRICE`, `SUBSCRIPTION_DURATION_DAYS`, `PAYMENT_PENDING_TTL_MINUTES`, `PAYMENT_REUSE_MINUTES`.
- `INVITE_LINK_TTL_HOURS` — срок действия ручной invite-ссылки.

Секреты хранятся только в окружении и не должны попадать в логи, Git или payload событий.

## Локальный запуск без Docker

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
# укажите DATABASE_URL на доступный PostgreSQL
alembic upgrade head
python -m teleport_bot.main
```

Проверки:

```bash
ruff check .
mypy src tests
pytest
```

## Docker

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm bot alembic upgrade head
docker compose up bot
```

В `docker-compose.yml` контейнер `bot` перед стартом выполняет `alembic upgrade head`, затем запускает `python -m teleport_bot.main`.

## Миграции

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Для production-проверки миграций используйте пустую PostgreSQL-базу и тот же `DATABASE_URL`, с которым будет запускаться приложение.

## YooKassa

Webhook настраивается в личном кабинете YooKassa:

```text
https://<PUBLIC_BASE_URL><YOOKASSA_WEBHOOK_PATH>
```

Поддерживаемые события:

- `payment.succeeded`
- `payment.canceled`
- `payment.waiting_for_capture`

Защита webhook:

- входящий payload не считается источником истины;
- сервис повторно получает платёж через YooKassa API;
- сверяются provider payment id, сумма, валюта и metadata (`user_id`, `telegram_id`, `product`);
- повторный webhook/idempotent callback не создаёт дублей подписки;
- секретный ключ YooKassa и карточные данные не сохраняются.

## Scheduler

APScheduler запускает ежедневную задачу обслуживания подписок:

- отправляет напоминания за 3 дня, за 1 день и в день окончания;
- пишет `subscription_reminders`, чтобы не отправлять один и тот же reminder повторно;
- переводит просроченные активные/ручные подписки в `expired`;
- логирует события в `event_logs`.

## Администраторский раздел

Команда `/admin` доступна только Telegram ID из `ADMIN_IDS`. Возможности:

- просмотр новых анкет и отметка review;
- поиск пользователей;
- статистика;
- ручная активация и выдача invite-ссылки;
- импорт, продление и отмена подписок;
- история пользователя;
- изменение runtime-настроек (`subscription_price`, `subscription_duration_days`, `circle_schedule`, `support_url`).

Все административные действия пишутся в `admin_action_logs`.

## Production deployment

1. Создать managed PostgreSQL или отдельный PostgreSQL-сервис.
2. Настроить секреты через secret manager / environment variables.
3. Запустить миграции `alembic upgrade head` перед rollout.
4. Разместить приложение за HTTPS reverse proxy.
5. Настроить YooKassa webhook на публичный HTTPS URL.
6. Настроить structured logs без DEBUG в production.
7. Включить health-check на `GET /health`.
8. Проверить `/start`, `/admin`, создание платежа, webhook и scheduler job на staging.
9. Настроить backup PostgreSQL и мониторинг ошибок Telegram/YooKassa.

## Итоговый аудит этапа production-hardening

Исправлено:

- Добавлен `pythonpath = ["src"]` для корректного запуска pytest из исходного дерева.
- Уточнена строгая типизация репозиториев SQLAlchemy: результаты `scalar/get` приводятся к доменным ORM-типам.
- Убран `type: ignore` в onboarding callback handlers за счёт проверки, что callback содержит обычное `Message`.
- Исправлена типизация aiogram/тестового отправителя для lifecycle-сервиса подписок.
- Исправлена типизация aiohttp timeout через `ClientTimeout`.
- Добавлены типы тестов и typed history DTO для административной истории.
- Исправлен тест административного лога, чтобы он использовал `AdminAction`, а не `EventType`.
- Обновлена документация по архитектуре, БД, Docker, миграциям, YooKassa, scheduler, админке и production deployment.

Оставшийся технический долг:

- В текущем окружении отсутствует `aiosqlite`, поэтому локальный pytest и SQLite-проверка Alembic не могут завершиться без установки dev-зависимостей.
- В текущем окружении отсутствует Docker CLI, поэтому контейнерные проверки не выполнялись.
- Для фактической проверки пустой PostgreSQL, downgrade и повторного upgrade нужен доступный PostgreSQL-инстанс.
- `APScheduler` не поставляет type stubs; для mypy используется scoped override `apscheduler.*`.

Рекомендации для следующих этапов:

- Добавить CI pipeline с PostgreSQL service container, coverage gate 85%, `ruff`, `mypy`, `pytest`, `alembic upgrade/downgrade/upgrade`.
- Добавить интеграционные тесты webhook YooKassa с mock HTTP gateway.
- Добавить проверку покрытия (`pytest --cov`) после добавления `pytest-cov` в dev-зависимости.
- Добавить миграционный smoke-test на реальной PostgreSQL в Docker/CI.

### Архитектурные исправления после аудита

- Webhook YooKassa теперь получает актуальный платеж провайдера до короткой транзакции БД, применяет статус под блокировкой строки платежа и только после commit запускает выдачу доступа в Telegram.
- Повторные webhook и ручная проверка платежа идемпотентны: уже примененный платеж не продлевает подписку повторно.
- Создание пользователя и анкеты переведено на PostgreSQL `INSERT ... ON CONFLICT DO UPDATE`.
- Полные invite-ссылки не сохраняются в `AdminActionLog` и `EventLog`; в payload допускаются только hash и длина ссылки.
- При ошибке Telegram API платеж остается успешным, подписка активной, а администраторы получают уведомление; пользователь может повторно запросить ссылку.
- При завершении приложения закрываются scheduler, aiohttp runner, Bot Session и SQLAlchemy Engine.

## Закрытая партнёрская реферальная система

Партнёры создаются только администратором в разделе `/admin` → «🤝 Партнёры» или через внутренний `ReferralService`; обычные пользователи не могут самостоятельно выпустить ссылку или стать партнёрами. Персональная ссылка имеет вид:

```text
https://t.me/{BOT_USERNAME}?start=ref_{referral_code}
```

`BOT_USERNAME` берётся из Telegram Bot API (`bot.get_me()`), а `referral_code` генерируется криптографически безопасно и не содержит последовательный ID партнёра.

Отслеживаются этапы воронки: первый старт по ссылке, завершение анкеты, создание платёжной ссылки и первая успешная оплата. Повторные анкеты, продления и повторные `/start` не увеличивают первые конверсии. Команда `/partner` доступна только активному партнёру и показывает только агрегированную собственную статистику без персональных данных привлечённых пользователей.

Админские действия по партнёрам логируются в `AdminActionLog`, события воронки — в `EventLog`. Физическое удаление партнёров не используется: деактивация сохраняет старую статистику и запрещает новые привязки по ссылке.
