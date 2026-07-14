from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.models.db import Payment, PaymentMethod, User
from teleport_bot.models.enums import PaymentMethodStatus, PaymentStatus


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_for_user(self, user_id: int) -> Payment | None:
        return await self.session.scalar(
            select(Payment).where(Payment.user_id == user_id).order_by(desc(Payment.created_at))
        )

    async def reusable_pending(self, user_id: int, reuse_minutes: int) -> Payment | None:
        cutoff = datetime.now(UTC) - timedelta(minutes=reuse_minutes)
        return await self.session.scalar(
            select(Payment)
            .where(Payment.user_id == user_id, Payment.status == PaymentStatus.PENDING.value)
            .where(Payment.confirmation_url.is_not(None), Payment.created_at >= cutoff)
            .order_by(desc(Payment.created_at))
        )

    async def get_by_provider_id(self, provider: str, provider_payment_id: str) -> Payment | None:
        return await self.session.scalar(
            select(Payment).where(
                Payment.provider == provider, Payment.provider_payment_id == provider_payment_id
            )
        )

    async def add(self, payment: Payment) -> Payment:
        self.session.add(payment)
        await self.session.flush()
        return payment


class PaymentMethodRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_saved_method(
        self, user: User, provider: str, provider_payment_method_id: str, title: str | None
    ) -> PaymentMethod:
        method = await self.session.scalar(
            select(PaymentMethod).where(
                PaymentMethod.provider == provider,
                PaymentMethod.provider_payment_method_id == provider_payment_method_id,
            )
        )
        now = datetime.now(UTC)
        if method is None:
            method = PaymentMethod(
                user_id=user.id,
                provider=provider,
                provider_payment_method_id=provider_payment_method_id,
                status=PaymentMethodStatus.ACTIVE.value,
                reusable=True,
                title=title,
                last_used_at=now,
            )
            self.session.add(method)
        else:
            method.status = PaymentMethodStatus.ACTIVE.value
            method.reusable = True
            method.title = title or method.title
            method.last_used_at = now
        await self.session.flush()
        return method
