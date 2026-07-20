from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from teleport_bot.config.settings import Settings
from teleport_bot.db.base import Base
from teleport_bot.models.db import Payment
from teleport_bot.models.enums import QuestionnaireStatus
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.yookassa import ProviderPayment
from teleport_bot.web import health


@dataclass
class TgUser:
    id: int
    username: str | None
    first_name: str
    last_name: str | None = None
    language_code: str | None = None


class FakeRequest:
    def __init__(self, payload: dict[str, Any], app: dict[str, Any] | None = None) -> None:
        self._payload = payload
        self.app = app or {}

    async def json(self) -> dict[str, Any]:
        return self._payload


class FakeGateway:
    def __init__(self, _: Settings) -> None:
        pass

    async def get_payment(self, provider_payment_id: str) -> ProviderPayment:
        return ProviderPayment(
            provider_payment_id=provider_payment_id,
            status="succeeded",
            amount=Decimal("990.00"),
            currency="RUB",
            metadata={
                "user_id": 1,
                "telegram_id": 1001,
                "product": "teleport_subscription",
                "idempotency_key": "recovered-idempotency-key",
                "subscription_duration_days": 30,
            },
        )


async def _session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_yookassa_webhook_step_1_logging_does_not_return_500() -> None:
    request = FakeRequest(
        {"event": "payment.ignored", "object": {"id": "pay_ignored"}},
    )

    response = await health.yookassa_webhook(cast(web.Request, request))

    assert response.status == 200


async def test_health_checks_database() -> None:
    engine, session_factory = await _session_factory()
    try:
        request = FakeRequest({}, {"session_factory": session_factory})
        response = await health.health(cast(web.Request, request))
        assert response.status == 200
    finally:
        await engine.dispose()


async def test_health_without_database_is_unhealthy() -> None:
    response = await health.health(cast(web.Request, FakeRequest({})))
    assert response.status == 503


async def test_yookassa_webhook_payment_succeeded_flow_passes_step_1(
    monkeypatch: Any,
) -> None:
    engine, session_factory = await _session_factory()
    try:
        async with session_factory() as session, session.begin():
            user, _ = await UserRepository(session).upsert_from_telegram(
                TgUser(1001, "user", "User")
            )
            session.add(
                Payment(
                    user_id=user.id,
                    provider="yookassa",
                    provider_payment_id="pay_succeeded",
                    idempotency_key="idem-pay-succeeded",
                    status="pending",
                    amount=Decimal("990.00"),
                    currency="RUB",
                    confirmation_url="https://pay.example/pay_succeeded",
                    description="Доступ в закрытое пространство Телепорт",
                    payment_metadata={
                        "user_id": user.id,
                        "telegram_id": user.telegram_id,
                        "product": "teleport_subscription",
                    },
                )
            )

        monkeypatch.setattr(health, "YooKassaGateway", FakeGateway)
        request = FakeRequest(
            {"event": "payment.succeeded", "object": {"id": "pay_succeeded"}},
            {"settings": Settings(), "session_factory": session_factory},
        )

        response = await health.yookassa_webhook(cast(web.Request, request))

        assert response.status == 200
        async with session_factory() as session:
            payment = await session.get(Payment, 1)
            assert payment is not None
            assert payment.status == "succeeded"
            assert payment.applied_to_subscription_at is not None
    finally:
        await engine.dispose()


async def test_yookassa_webhook_recovers_payment_missing_after_failed_commit(
    monkeypatch: Any,
) -> None:
    engine, session_factory = await _session_factory()
    try:
        async with session_factory() as session, session.begin():
            user, _ = await UserRepository(session).upsert_from_telegram(
                TgUser(1001, "user", "User")
            )
            user.questionnaire.status = QuestionnaireStatus.COMPLETED.value

        monkeypatch.setattr(health, "YooKassaGateway", FakeGateway)
        request = FakeRequest(
            {"event": "payment.succeeded", "object": {"id": "orphan_payment"}},
            {"settings": Settings(), "session_factory": session_factory},
        )
        response = await health.yookassa_webhook(cast(web.Request, request))
        assert response.status == 200
        async with session_factory() as session:
            payment = await session.scalar(select(Payment))
            assert payment is not None
            assert payment.provider_payment_id == "orphan_payment"
            assert payment.applied_to_subscription_at is not None
    finally:
        await engine.dispose()
