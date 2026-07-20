from datetime import UTC, datetime

from aiogram import Bot
from aiohttp import web
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.stdlib import get_logger

from teleport_bot.config.settings import Settings
from teleport_bot.models.enums import EventType
from teleport_bot.repositories.events import EventRepository
from teleport_bot.repositories.payments import PaymentRepository
from teleport_bot.repositories.settings import SettingsRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.admin_notifications import AdminNotifier
from teleport_bot.services.payments import PaymentService, PaymentValidationError
from teleport_bot.services.yookassa import YooKassaGateway

logger = get_logger(__name__)


async def health(request: web.Request) -> web.Response:
    if request.app.get("ready", True) is not True:
        return web.json_response({"status": "unhealthy", "application": "not_ready"}, status=503)
    bot: Bot | None = request.app.get("bot")
    if bot is not None and bool(getattr(bot.session, "closed", False)):
        return web.json_response({"status": "unhealthy", "telegram": "session_closed"}, status=503)
    factory: async_sessionmaker[AsyncSession] | None = request.app.get("session_factory")
    if factory is None:
        return web.json_response({"status": "degraded", "database": "not_configured"}, status=503)
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("health_check_failed", dependency="database", error=type(exc).__name__)
        return web.json_response({"status": "unhealthy", "database": "unavailable"}, status=503)
    return web.json_response({"status": "ok", "database": "ok"})


async def payment_open(request: web.Request) -> web.Response:
    idempotency_key = str(request.match_info.get("idempotency_key") or "")
    if not idempotency_key or len(idempotency_key) > 128:
        raise web.HTTPNotFound()
    settings: Settings = request.app["settings"]
    factory: async_sessionmaker[AsyncSession] = request.app["session_factory"]
    redirect_url: str | None = None
    async with factory() as session:
        async with session.begin():
            payment = await PaymentRepository(session).get_by_idempotency_key_for_update(
                idempotency_key
            )
            if payment is None or not payment.confirmation_url:
                raise web.HTTPNotFound()
            redirect_url = payment.confirmation_url
            if payment.confirmation_opened_at is None:
                payment.confirmation_opened_at = datetime.now(UTC)
                user = await UserRepository(session).get_by_id(payment.user_id)
                if user is not None:
                    events = EventRepository(session)
                    await events.add(
                        EventType.PAYMENT_LINK_OPENED,
                        user,
                        {"payment_id": payment.id},
                    )
                    bot: Bot | None = request.app.get("bot")
                    if bot is not None:
                        await AdminNotifier(
                            bot, settings.admin_telegram_ids, events
                        ).payment_link_opened(user, payment)
    raise web.HTTPFound(location=redirect_url)


async def yookassa_webhook(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning(
            "STEP 1 webhook received",
            status="failed",
            reason="invalid_json",
            error=str(exc),
        )
        return web.json_response({"error": "invalid_json"}, status=400)
    event = payload.get("event")
    provider_payment_id = str((payload.get("object") or {}).get("id") or "")
    logger.info(
        "STEP 1 webhook received",
        status="ok",
        webhook_event=event,
        provider_payment_id=provider_payment_id or None,
    )
    if event not in {
        "payment.succeeded",
        "payment.canceled",
        "payment.waiting_for_capture",
    }:
        logger.info("webhook processing stopped", reason="ignored_event", webhook_event=event)
        return web.json_response({"status": "ignored"})
    if not provider_payment_id:
        logger.warning(
            "webhook processing stopped", reason="payment_id_required", webhook_event=event
        )
        return web.json_response({"error": "payment_id_required"}, status=400)
    settings: Settings = request.app["settings"]
    factory: async_sessionmaker[AsyncSession] = request.app["session_factory"]
    gateway = YooKassaGateway(settings)
    provider_payment = await gateway.get_payment(provider_payment_id)
    deliver_user_id: int | None = None
    async with factory() as session:
        async with session.begin():
            runtime_settings = await SettingsRepository(session).resolved(settings)
            payment = await PaymentRepository(session).get_by_provider_id_for_update(
                "yookassa", provider_payment_id
            )
            if payment is None:
                try:
                    payment = await PaymentService(
                        session, runtime_settings, gateway
                    ).recover_provider_payment(provider_payment)
                except PaymentValidationError as exc:
                    logger.warning(
                        "webhook processing stopped",
                        reason="unknown_payment",
                        error=type(exc).__name__,
                        provider_payment_id=provider_payment_id,
                    )
                    return web.json_response({"status": "unknown_payment"}, status=202)
            service = PaymentService(session, runtime_settings, gateway)
            was_applied = payment.applied_to_subscription_at is not None
            try:
                await service.apply_provider_status(payment, provider_payment)
            except PaymentValidationError as exc:
                logger.warning(
                    "webhook processing stopped",
                    reason="validation_failed",
                    error=exc.__class__.__name__,
                    provider_payment_id=provider_payment_id,
                    payment_id=payment.id,
                    user_id=payment.user_id,
                )
                return web.json_response({"status": "validation_failed"}, status=202)
            logger.info(
                "STEP 2 payment applied",
                payment_id=payment.id,
                user_id=payment.user_id,
                provider_status=provider_payment.status,
                payment_status=payment.status,
                applied_to_subscription=payment.applied_to_subscription_at is not None,
                was_already_applied=was_applied,
            )
            if not was_applied and payment.applied_to_subscription_at is not None:
                deliver_user_id = payment.user_id
                logger.info(
                    "STEP 3 subscription activated",
                    payment_id=payment.id,
                    user_id=payment.user_id,
                )
            else:
                logger.info(
                    "webhook access delivery skipped",
                    reason="payment_not_newly_applied",
                    payment_id=payment.id,
                    user_id=payment.user_id,
                )
    bot: Bot | None = request.app.get("bot")
    if bot is None:
        logger.warning("webhook access delivery skipped", reason="bot_not_configured")
    elif deliver_user_id is None:
        logger.info("webhook access delivery skipped", reason="no_user_to_deliver")
    else:
        async with factory() as session:
            user = await UserRepository(session).get_by_id(deliver_user_id)
            if user is None:
                logger.warning(
                    "webhook access delivery skipped",
                    reason="user_not_found",
                    user_id=deliver_user_id,
                )
            else:
                runtime_settings = await SettingsRepository(session).resolved(settings)
                service = PaymentService(session, runtime_settings, gateway)
                payment = await PaymentRepository(session).get_by_provider_id(
                    "yookassa", provider_payment_id
                )
                if payment is not None:
                    await service.notify_payment_succeeded(bot, user, payment)
                await service.deliver_access_after_commit(bot, user)
                await session.commit()
    return web.json_response({"status": "ok"})


def create_health_app(
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    bot: Bot | None = None,
) -> web.Application:
    app = web.Application()
    if settings is not None:
        app["settings"] = settings
    if session_factory is not None:
        app["session_factory"] = session_factory
    if bot is not None:
        app["bot"] = bot
    app["ready"] = False
    app.router.add_get("/health", health)
    app.router.add_get("/payments/open/{idempotency_key}", payment_open)
    path = (
        settings.yookassa_webhook_path if settings is not None else "/webhooks/yookassa"
    )
    app.router.add_post(path, yookassa_webhook)
    return app
