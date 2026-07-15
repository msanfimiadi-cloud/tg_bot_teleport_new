from aiogram import Bot
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.stdlib import get_logger

from teleport_bot.config.settings import Settings
from teleport_bot.models.db import User
from teleport_bot.repositories.payments import PaymentRepository
from teleport_bot.services.payments import PaymentService
from teleport_bot.services.yookassa import YooKassaGateway

logger = get_logger(__name__)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


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
            payment = await PaymentRepository(session).get_by_provider_id_for_update(
                "yookassa", provider_payment_id
            )
            if payment is None:
                logger.warning(
                    "webhook processing stopped",
                    reason="unknown_payment",
                    provider_payment_id=provider_payment_id,
                )
                return web.json_response({"status": "unknown_payment"}, status=202)
            service = PaymentService(session, settings, gateway)
            was_applied = payment.applied_to_subscription_at is not None
            try:
                await service.apply_provider_status(payment, provider_payment)
            except Exception as exc:
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
            if payment.applied_to_subscription_at is not None and not was_applied:
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
            user = await session.get(User, deliver_user_id)
            if user is None:
                logger.warning(
                    "webhook access delivery skipped",
                    reason="user_not_found",
                    user_id=deliver_user_id,
                )
            else:
                await PaymentService(
                    session, settings, gateway
                ).deliver_access_after_commit(bot, user)
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
    app.router.add_get("/health", health)
    path = (
        settings.yookassa_webhook_path if settings is not None else "/webhooks/yookassa"
    )
    app.router.add_post(path, yookassa_webhook)
    return app
