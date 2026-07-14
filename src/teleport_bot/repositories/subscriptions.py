from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.models.db import Subscription, User
from teleport_bot.models.enums import ActivationSource, SubscriptionStatus


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user_id(self, user_id: int) -> Subscription | None:
        return await self.session.scalar(
            select(Subscription).where(Subscription.user_id == user_id)
        )

    async def activate_manual(
        self, user: User, expires_at: datetime, activated_by: int | None = None
    ) -> Subscription:
        subscription = await self.get_for_user_id(user.id)
        now = datetime.now(UTC)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if subscription is None:
            subscription = Subscription(
                user_id=user.id,
                status=SubscriptionStatus.MANUAL.value,
                started_at=now,
                expires_at=expires_at,
                activated_by=activated_by,
                activation_source=ActivationSource.MANUAL.value,
            )
            self.session.add(subscription)
        else:
            subscription.status = SubscriptionStatus.MANUAL.value
            subscription.started_at = subscription.started_at or now
            subscription.expires_at = expires_at
            subscription.activated_by = activated_by
            subscription.activation_source = ActivationSource.MANUAL.value
        await self.session.flush()
        return subscription

    @staticmethod
    def is_active(subscription: Subscription | None) -> bool:
        if subscription is None:
            return False
        if subscription.status not in {
            SubscriptionStatus.ACTIVE.value,
            SubscriptionStatus.MANUAL.value,
        }:
            return False
        return subscription.expires_at is None or subscription.expires_at > datetime.now(UTC)
