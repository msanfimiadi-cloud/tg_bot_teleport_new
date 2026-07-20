import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote, urlparse

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.stdlib import get_logger

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
from teleport_bot.repositories.payments import (
    PaymentMethodRepository,
    PaymentRepository,
)
from teleport_bot.repositories.subscriptions import SubscriptionRepository
from teleport_bot.repositories.users import UserRepository
from teleport_bot.services.access import AccessService
from teleport_bot.services.admin_notifications import AdminNotifier
from teleport_bot.services.referrals import ReferralService
from teleport_bot.services.telegram import TelegramService
from teleport_bot.services.yookassa import (
    ProviderPayment,
    YooKassaGatewayProtocol,
    new_idempotency_key,
)

logger = get_logger(__name__)

PROVIDER = "yookassa"
PRODUCT = "teleport_subscription"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PaymentError(RuntimeError):
    pass


class PaymentValidationError(PaymentError):
    pass


class PaymentContactRequiredError(PaymentError):
    pass


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if len(normalized) > 320 or not _EMAIL_RE.fullmatch(normalized):
        raise PaymentValidationError("invalid_email")
    return normalized


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "<invalid_email>"


def payment_checkout_url(payment: Payment, settings: Settings) -> tuple[str, bool]:
    base_url = settings.public_base_url or settings.webhook_host
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            token = quote(payment.idempotency_key, safe="")
            return f"{base_url.rstrip('/')}/payments/open/{token}", True
    return payment.confirmation_url or settings.yookassa_return_url, False


class PaymentService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        gateway: YooKassaGatewayProtocol,
    ) -> None:
        self.session = session
        self.settings = settings
        self.gateway = gateway
        self.payments = PaymentRepository(session)
        self.events = EventRepository(session)

    async def create_or_reuse_payment(self, telegram_id: int) -> Payment:
        user = await UserRepository(self.session).get_by_telegram_id_for_update(telegram_id)
        if user is None:
            raise PaymentError("user_not_found")
        if user.questionnaire.status != QuestionnaireStatus.COMPLETED.value:
            raise PaymentError("questionnaire_not_completed")
        reusable = await self.payments.reusable_pending(
            user.id, self.settings.payment_reuse_minutes
        )
        if reusable and not self._is_expired(reusable):
            await self.events.add(
                EventType.PAYMENT_REUSED, user, {"payment_id": reusable.id}
            )
            return reusable
        key = new_idempotency_key()
        if not user.email:
            raise PaymentContactRequiredError("email_required")
        metadata = {
            "user_id": user.id,
            "telegram_id": user.telegram_id,
            "product": PRODUCT,
            "idempotency_key": key,
            "subscription_duration_days": self.settings.subscription_duration_days,
        }
        provider = await self.gateway.create_payment(
            idempotency_key=key, metadata=metadata, customer_email=user.email
        )
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
            {
                "payment_id": payment.id,
                "provider_payment_id": payment.provider_payment_id,
            },
        )
        return payment

    async def recover_provider_payment(self, provider: ProviderPayment) -> Payment:
        """Recover a YooKassa payment created before a failed local DB commit."""
        metadata = provider.metadata or {}
        try:
            user_id = int(metadata["user_id"])
            telegram_id = int(metadata["telegram_id"])
            idempotency_key = str(metadata["idempotency_key"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PaymentValidationError("recovery_metadata") from exc
        if metadata.get("product") != PRODUCT or not idempotency_key:
            raise PaymentValidationError("recovery_metadata")
        user = await UserRepository(self.session).get_by_telegram_id_for_update(telegram_id)
        if (
            user is None
            or user.id != user_id
            or user.questionnaire.status != QuestionnaireStatus.COMPLETED.value
        ):
            raise PaymentValidationError("recovery_user")
        payment = Payment(
            user_id=user.id,
            provider=PROVIDER,
            provider_payment_id=provider.provider_payment_id,
            idempotency_key=idempotency_key,
            status=provider.status,
            amount=provider.amount,
            currency=provider.currency,
            confirmation_url=provider.confirmation_url,
            description=self.settings.subscription_description,
            payment_metadata=dict(metadata),
            expires_at=datetime.now(UTC)
            + timedelta(minutes=self.settings.payment_pending_ttl_minutes),
        )
        await self.payments.add(payment)
        await self.events.add(
            EventType.PAYMENT_CREATED,
            user,
            {
                "payment_id": payment.id,
                "provider_payment_id": payment.provider_payment_id,
                "recovered": True,
            },
        )
        return payment

    async def check_latest_payment(self, telegram_id: int) -> Payment | None:
        user = await UserRepository(self.session).get_by_telegram_id(telegram_id)
        if user is None:
            raise PaymentError("user_not_found")
        payment = await self.payments.latest_for_user(user.id)
        if payment is None:
            return None
        provider_payment_id = payment.provider_payment_id
        provider = await self.gateway.get_payment(provider_payment_id)
        await self.events.add(
            EventType.PAYMENT_STATUS_CHECKED,
            user,
            {"payment_id": payment.id, "status": provider.status},
        )
        locked = await self.payments.get_by_provider_id_for_update(
            PROVIDER, provider_payment_id
        )
        if locked is None:
            return None
        await self.apply_provider_status(locked, provider)
        return locked

    async def apply_provider_status(
        self, payment: Payment, provider: ProviderPayment
    ) -> None:
        user = await UserRepository(self.session).get_by_id(payment.user_id)
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
            await self.events.add(
                EventType.PAYMENT_CANCELED, user, {"payment_id": payment.id}
            )
        elif provider.status == PaymentStatus.WAITING_FOR_CAPTURE.value:
            payment.status = PaymentStatus.WAITING_FOR_CAPTURE.value
        else:
            payment.status = provider.status
        await self.session.flush()

    def _validate(
        self, payment: Payment, provider: ProviderPayment, user: User
    ) -> None:
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

    async def _succeed(
        self, payment: Payment, provider: ProviderPayment, user: User
    ) -> None:
        if payment.applied_to_subscription_at is not None:
            payment.status = PaymentStatus.SUCCEEDED.value
            return
        now = datetime.now(UTC)
        payment.status = PaymentStatus.SUCCEEDED.value
        payment.paid_at = payment.paid_at or now
        payment.payment_method_saved = provider.payment_method_saved
        payment.provider_payment_method_id = provider.payment_method_id
        repo = SubscriptionRepository(self.session)
        sub = await repo.get_for_user_id_for_update(user.id)
        event = EventType.SUBSCRIPTION_ACTIVATED
        if sub is None:
            from teleport_bot.models.db import Subscription

            sub = Subscription(user_id=user.id)
            self.session.add(sub)
        elif (
            SubscriptionRepository.is_active(sub)
            and sub.expires_at
            and sub.expires_at > now
        ):
            now = sub.expires_at
            event = EventType.SUBSCRIPTION_EXTENDED
        user.subscription = sub
        sub.status = SubscriptionStatus.ACTIVE.value
        sub.activation_source = ActivationSource.YOOKASSA.value
        sub.payment_provider = PROVIDER
        sub.last_payment_at = payment.paid_at
        sub.started_at = (
            payment.paid_at
            if event == EventType.SUBSCRIPTION_ACTIVATED
            else sub.started_at
        )
        try:
            duration_days = int(
                payment.payment_metadata.get(
                    "subscription_duration_days", self.settings.subscription_duration_days
                )
            )
        except (TypeError, ValueError):
            duration_days = self.settings.subscription_duration_days
        if not 1 <= duration_days <= 3650:
            raise PaymentValidationError("subscription_duration_days")
        sub.expires_at = now + timedelta(days=duration_days)
        await repo.reset_reminders(sub)
        sub.last_payment = payment
        payment.applied_to_subscription_at = datetime.now(UTC)
        if provider.payment_method_saved and provider.payment_method_id:
            await PaymentMethodRepository(self.session).upsert_saved_method(
                user,
                PROVIDER,
                provider.payment_method_id,
                provider.payment_method_title,
            )
            await self.events.add(
                EventType.PAYMENT_METHOD_SAVED, user, {"payment_id": payment.id}
            )
        await self.events.add(
            EventType.PAYMENT_SUCCEEDED, user, {"payment_id": payment.id}
        )
        await ReferralService(self.session).mark_first_payment_succeeded(user, payment)
        await self.events.add(
            event,
            user,
            {"payment_id": payment.id, "expires_at": sub.expires_at.isoformat()},
        )

    def _is_expired(self, payment: Payment) -> bool:
        return bool(payment.expires_at and payment.expires_at <= datetime.now(UTC))

    async def notify_payment_succeeded(self, bot: Bot, user: User, payment: Payment) -> None:
        if payment.success_notified_at is not None:
            return
        await AdminNotifier(
            bot, self.settings.admin_telegram_ids, self.events
        ).payment_succeeded(user, payment)
        payment.success_notified_at = datetime.now(UTC)
        await self.session.flush()

    async def deliver_access_after_commit(self, bot: Bot, user: User) -> bool:
        try:
            if self.settings.private_chat_id is None:
                logger.warning(
                    "access delivery stopped",
                    reason="private_chat_id_not_configured",
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                )
                raise RuntimeError("private_chat_id_not_configured")
            logger.info(
                "STEP 4 access service called",
                user_id=user.id,
                telegram_id=user.telegram_id,
                private_chat_id=self.settings.private_chat_id,
            )
            result = await AccessService(
                self.session, TelegramService(bot)
            ).send_paid_invite(
                user.telegram_id,
                self.settings.private_chat_id,
                invite_link_ttl_hours=self.settings.invite_link_ttl_hours,
            )
            await self.events.add(
                (
                    EventType.ACCESS_ALREADY_PRESENT
                    if result.already_member
                    else EventType.INVITE_LINK_CREATED
                ),
                user,
            )
            await AdminNotifier(
                bot, self.settings.admin_telegram_ids, self.events
            ).access_delivered(user, already_member=result.already_member)
            logger.info(
                "access delivery completed",
                user_id=user.id,
                telegram_id=user.telegram_id,
                sent=result.sent,
                already_member=result.already_member,
                invite_created=result.invite_link is not None,
            )
            return True
        except Exception as exc:
            logger.warning(
                "access delivery stopped",
                reason="exception",
                error=exc.__class__.__name__,
                user_id=user.id,
                telegram_id=user.telegram_id,
            )
            await self.events.add(
                EventType.ACCESS_DELIVERY_FAILED,
                user,
                {"error": exc.__class__.__name__},
            )
            await AdminNotifier(
                bot, self.settings.admin_telegram_ids, self.events
            )._send(f"Не удалось выдать доступ после оплаты: {user.telegram_id}", user)
            if isinstance(exc, TelegramAPIError):
                return False
            return False


class RecurringPaymentService:
    async def create_recurring_payment(self) -> None:
        raise NotImplementedError("Recurring payments are not enabled yet")
