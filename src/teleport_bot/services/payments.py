from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.config.settings import Settings
from teleport_bot.models.db import Payment, User
from teleport_bot.models.enums import (
    ActivationSource,
    EventType,
    PaymentStatus,
    QuestionnaireStatus,
    SubscriptionStatus,
)
from teleport_bot.repositories.events import EventRepository
from teleport_bot.repositories.payments import PaymentMethodRepository, PaymentRepository
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.access import AccessService
from teleport_bot.services.admin_notifications import AdminNotifier
from teleport_bot.services.telegram import TelegramService
from teleport_bot.services.yookassa import (
    ProviderPayment,
    YooKassaGatewayProtocol,
    new_idempotency_key,
)

PROVIDER = "yookassa"
PRODUCT = "teleport_subscription"


class PaymentError(RuntimeError):
    pass


class PaymentValidationError(PaymentError):
    pass


class PaymentService:
    def __init__(
        self, session: AsyncSession, settings: Settings, gateway: YooKassaGatewayProtocol
    ) -> None:
        self.session = session
        self.settings = settings
        self.gateway = gateway
        self.payments = PaymentRepository(session)
        self.events = EventRepository(session)

    async def create_or_reuse_payment(self, telegram_id: int) -> Payment:
        user = await UserRepository(self.session).get_by_telegram_id(telegram_id)
        if user is None:
            raise PaymentError("user_not_found")
        if user.questionnaire.status != QuestionnaireStatus.COMPLETED.value:
            raise PaymentError("questionnaire_not_completed")
        if SubscriptionRepository.is_active(user.subscription):
            raise PaymentError("subscription_active")
        reusable = await self.payments.reusable_pending(
            user.id, self.settings.payment_reuse_minutes
        )
        if reusable and not self._is_expired(reusable):
            await self.events.add(EventType.PAYMENT_REUSED, user, {"payment_id": reusable.id})
            return reusable
        key = new_idempotency_key()
        metadata = {"user_id": user.id, "telegram_id": user.telegram_id, "product": PRODUCT}
        provider = await self.gateway.create_payment(idempotency_key=key, metadata=metadata)
        payment = Payment(
            user_id=user.id,
            provider=PROVIDER,
            provider_payment_id=provider.provider_payment_id,
            idempotency_key=key,
            status=provider.status,
            amount=self.settings.subscription_price,
            currency=self.settings.yookassa_currency,
            confirmation_url=provider.confirmation_url,
            description=self.settings.subscription_description,
            is_recurring=False,
            save_payment_method_requested=self.settings.payment_save_method_enabled,
            expires_at=datetime.now(UTC)
            + timedelta(minutes=self.settings.payment_pending_ttl_minutes),
            payment_metadata=metadata,
        )
        await self.payments.add(payment)
        await self.events.add(
            EventType.PAYMENT_CREATED,
            user,
            {"payment_id": payment.id, "provider_payment_id": payment.provider_payment_id},
        )
        return payment

    async def check_latest_payment(self, telegram_id: int) -> Payment | None:
        user = await UserRepository(self.session).get_by_telegram_id(telegram_id)
        if user is None:
            raise PaymentError("user_not_found")
        payment = await self.payments.latest_for_user(user.id)
        if payment is None:
            return None
        provider = await self.gateway.get_payment(payment.provider_payment_id)
        await self.events.add(
            EventType.PAYMENT_STATUS_CHECKED,
            user,
            {"payment_id": payment.id, "status": provider.status},
        )
        await self.apply_provider_status(payment, provider)
        return payment

    async def apply_provider_status(self, payment: Payment, provider: ProviderPayment) -> None:
        user = payment.user or await UserRepository(self.session).get_by_id(payment.user_id)
        if user is None:
            raise PaymentValidationError("user_not_found")
        self._validate(payment, provider, user)
        if provider.status == PaymentStatus.SUCCEEDED.value:
            await self._succeed(payment, provider, user)
        elif provider.status == PaymentStatus.CANCELED.value:
            payment.status = PaymentStatus.CANCELED.value
            payment.canceled_at = datetime.now(UTC)
            payment.failure_code = provider.failure_code
            payment.failure_message = provider.failure_message
            await self.events.add(EventType.PAYMENT_CANCELED, user, {"payment_id": payment.id})
        elif provider.status == PaymentStatus.WAITING_FOR_CAPTURE.value:
            payment.status = PaymentStatus.WAITING_FOR_CAPTURE.value
        else:
            payment.status = provider.status
        await self.session.flush()

    def _validate(self, payment: Payment, provider: ProviderPayment, user: User) -> None:
        errors = []
        if provider.provider_payment_id != payment.provider_payment_id:
            errors.append("payment_id")
        if provider.amount != Decimal(payment.amount):
            errors.append("amount")
        if provider.currency != payment.currency:
            errors.append("currency")
        md = provider.metadata or {}
        if (
            int(md.get("user_id", -1)) != user.id
            or int(md.get("telegram_id", -1)) != user.telegram_id
            or md.get("product") != PRODUCT
        ):
            errors.append("metadata")
        if errors:
            raise PaymentValidationError(",".join(errors))

    async def _succeed(self, payment: Payment, provider: ProviderPayment, user: User) -> None:
        if payment.applied_to_subscription_at is not None:
            payment.status = PaymentStatus.SUCCEEDED.value
            return
        now = datetime.now(UTC)
        payment.status = PaymentStatus.SUCCEEDED.value
        payment.paid_at = payment.paid_at or now
        payment.payment_method_saved = provider.payment_method_saved
        payment.provider_payment_method_id = provider.payment_method_id
        repo = SubscriptionRepository(self.session)
        sub = await repo.get_for_user_id(user.id)
        event = EventType.SUBSCRIPTION_ACTIVATED
        if sub is None:
            from teleport_bot.models.db import Subscription

            sub = Subscription(user_id=user.id)
            self.session.add(sub)
        elif SubscriptionRepository.is_active(sub) and sub.expires_at and sub.expires_at > now:
            now = sub.expires_at
            event = EventType.SUBSCRIPTION_EXTENDED
        sub.status = SubscriptionStatus.ACTIVE.value
        sub.activation_source = ActivationSource.YOOKASSA.value
        sub.payment_provider = PROVIDER
        sub.last_payment_at = payment.paid_at
        sub.started_at = (
            payment.paid_at if event == EventType.SUBSCRIPTION_ACTIVATED else sub.started_at
        )
        sub.expires_at = now + timedelta(days=self.settings.subscription_duration_days)
        sub.last_payment = payment
        payment.applied_to_subscription_at = datetime.now(UTC)
        if provider.payment_method_saved and provider.payment_method_id:
            await PaymentMethodRepository(self.session).upsert_saved_method(
                user, PROVIDER, provider.payment_method_id, provider.payment_method_title
            )
            await self.events.add(EventType.PAYMENT_METHOD_SAVED, user, {"payment_id": payment.id})
        await self.events.add(EventType.PAYMENT_SUCCEEDED, user, {"payment_id": payment.id})
        await self.events.add(
            event, user, {"payment_id": payment.id, "expires_at": sub.expires_at.isoformat()}
        )

    def _is_expired(self, payment: Payment) -> bool:
        return bool(payment.expires_at and payment.expires_at <= datetime.now(UTC))

    async def deliver_access_after_commit(self, bot: Bot, user: User) -> None:
        try:
            if self.settings.private_chat_id is None:
                raise RuntimeError("private_chat_id_not_configured")
            result = await AccessService(self.session, TelegramService(bot)).send_paid_invite(
                user.telegram_id, self.settings.private_chat_id
            )
            await self.events.add(
                EventType.ACCESS_ALREADY_PRESENT
                if result.already_member
                else EventType.INVITE_LINK_CREATED,
                user,
            )
        except Exception as exc:
            await self.events.add(
                EventType.ACCESS_DELIVERY_FAILED, user, {"error": exc.__class__.__name__}
            )
            await AdminNotifier(bot, self.settings.admin_telegram_ids, self.events)._send(
                f"Не удалось выдать доступ после оплаты: {user.telegram_id}", user
            )
            if isinstance(exc, TelegramAPIError):
                raise


class RecurringPaymentService:
    async def create_recurring_payment(self) -> None:
        raise NotImplementedError("Recurring payments are not enabled yet")
