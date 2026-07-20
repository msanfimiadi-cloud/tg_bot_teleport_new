from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from teleport_bot.config.settings import Settings
from teleport_bot.db.base import Base
from teleport_bot.models.db import Payment
from teleport_bot.models.enums import QuestionnaireStatus
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.payments import (
    PaymentContactRequiredError,
    PaymentService,
    PaymentValidationError,
    normalize_email,
)
from teleport_bot.services.yookassa import ProviderPayment, YooKassaGateway, _safe_json


@dataclass
class TgUser:
    id: int
    username: str | None
    first_name: str
    last_name: str | None = None
    language_code: str | None = None


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_payment(
        self,
        *,
        idempotency_key: str,
        metadata: dict[str, Any],
        customer_email: str | None = None,
        customer_phone: str | None = None,
    ) -> ProviderPayment:
        self.calls.append(
            {
                "idempotency_key": idempotency_key,
                "metadata": metadata,
                "customer_email": customer_email,
                "customer_phone": customer_phone,
            }
        )
        return ProviderPayment(
            provider_payment_id="pay_1",
            status="pending",
            amount=Decimal("1234.00"),
            currency="RUB",
            confirmation_url="https://pay.example/1",
        )

    async def get_payment(self, provider_payment_id: str) -> ProviderPayment:
        raise NotImplementedError


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def test_yookassa_payload_contains_valid_receipt_and_settings() -> None:
    settings = Settings(
        subscription_price=Decimal("1234.00"),
        yookassa_currency="RUB",
        subscription_title="Клуб Телепорт",
        subscription_description="Описание",
        yookassa_vat_code=2,
        yookassa_payment_mode="partial_payment",
        yookassa_payment_subject="commodity",
    )
    payload = YooKassaGateway(settings)._build_payment_payload(
        metadata={"user_id": 1}, customer_email="user@example.com"
    )

    assert payload["amount"] == {"value": "1234.00", "currency": "RUB"}
    assert payload["receipt"]["customer"] == {"email": "user@example.com"}
    item = payload["receipt"]["items"][0]
    assert item["description"] == "Клуб Телепорт"
    assert item["quantity"] == "1"
    assert item["amount"] == payload["amount"]
    assert item["amount"] is not payload["amount"]
    assert item["vat_code"] == 2
    assert item["payment_mode"] == "partial_payment"
    assert item["payment_subject"] == "commodity"


def test_yookassa_payload_rejects_missing_email_or_phone() -> None:
    with pytest.raises(ValueError, match="receipt_customer_contact_required"):
        YooKassaGateway(Settings())._build_payment_payload(metadata={})


@pytest.mark.parametrize("email", ["bad", "a@", "a b@example.com"])
def test_invalid_email_rejected(email: str) -> None:
    with pytest.raises(PaymentValidationError):
        normalize_email(email)


async def test_payment_requires_saved_email(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(10, "not-email", "A"))
        user.questionnaire.status = QuestionnaireStatus.COMPLETED.value
        gateway = FakeGateway()

        with pytest.raises(PaymentContactRequiredError):
            await PaymentService(session, Settings(), gateway).create_or_reuse_payment(10)

        assert gateway.calls == []


async def test_repeat_payment_uses_saved_email(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(11, "not-email", "A"))
        user.questionnaire.status = QuestionnaireStatus.COMPLETED.value
        user.email = "saved@example.com"
        gateway = FakeGateway()

        payment = await PaymentService(session, Settings(), gateway).create_or_reuse_payment(11)

        assert payment.confirmation_url == "https://pay.example/1"
        assert gateway.calls[0]["customer_email"] == "saved@example.com"


async def test_successful_payment_updates_loaded_user_subscription(session_factory: Any) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(12, "user", "A"))
        user.questionnaire.status = QuestionnaireStatus.COMPLETED.value
        payment = Payment(
            user_id=user.id,
            provider="yookassa",
            provider_payment_id="pay_loaded_user",
            idempotency_key="idem_loaded_user",
            status="pending",
            amount=Decimal("990.00"),
            currency="RUB",
            payment_metadata={
                "user_id": user.id,
                "telegram_id": user.telegram_id,
                "product": "teleport_subscription",
                "subscription_duration_days": 30,
            },
        )
        session.add(payment)
        await session.flush()
        provider = ProviderPayment(
            provider_payment_id=payment.provider_payment_id,
            status="succeeded",
            amount=Decimal("990.00"),
            currency="RUB",
            paid=True,
            metadata=payment.payment_metadata,
        )
        await PaymentService(session, Settings(), FakeGateway()).apply_provider_status(
            payment, provider
        )
        assert user.subscription is not None
        assert user.subscription.status == "active"


async def test_successful_renewal_extends_active_subscription_from_current_expiry(
    session_factory: Any,
) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(13, "renew", "A"))
        user.questionnaire.status = QuestionnaireStatus.COMPLETED.value
        current_expiry = datetime.now(UTC) + timedelta(days=12)
        await SubscriptionRepository(session).activate_manual(user, current_expiry)
        payment = Payment(
            user_id=user.id,
            provider="yookassa",
            provider_payment_id="pay_renew_active",
            idempotency_key="idem_renew_active",
            status="pending",
            amount=Decimal("990.00"),
            currency="RUB",
            payment_metadata={
                "user_id": user.id,
                "telegram_id": user.telegram_id,
                "product": "teleport_subscription",
                "subscription_duration_days": 30,
            },
        )
        session.add(payment)
        await session.flush()
        provider = ProviderPayment(
            provider_payment_id=payment.provider_payment_id,
            status="succeeded",
            amount=Decimal("990.00"),
            currency="RUB",
            paid=True,
            metadata=payment.payment_metadata,
        )

        await PaymentService(session, Settings(), FakeGateway()).apply_provider_status(
            payment, provider
        )

        assert user.subscription is not None
        assert user.subscription.status == "active"
        assert user.subscription.expires_at == current_expiry + timedelta(days=30)


def test_email_is_masked_in_safe_log_payload() -> None:
    safe = _safe_json({"description": "receipt for person@example.com"})

    assert "person@example.com" not in str(safe)
    assert "p***@example.com" in str(safe)
