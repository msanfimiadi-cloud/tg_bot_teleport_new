from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.models.db import Subscription, SubscriptionReminder, User
from teleport_bot.models.enums import ActivationSource, SubscriptionStatus


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user_id(self, user_id: int) -> Subscription | None:
        return cast(
            Subscription | None,
            await self.session.scalar(select(Subscription).where(Subscription.user_id == user_id)),
        )

    async def get_for_user_id_for_update(self, user_id: int) -> Subscription | None:
        return cast(
            Subscription | None,
            await self.session.scalar(
                select(Subscription).where(Subscription.user_id == user_id).with_for_update()
            ),
        )

    async def activate_manual(
        self,
        user: User,
        expires_at: datetime,
        activated_by: int | None = None,
        activation_source: str = ActivationSource.MANUAL.value,
    ) -> Subscription:
        subscription = await self.get_for_user_id_for_update(user.id)
        previous_expires_at = subscription.expires_at if subscription is not None else None
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
                activation_source=activation_source,
            )
            self.session.add(subscription)
        else:
            subscription.status = SubscriptionStatus.MANUAL.value
            subscription.started_at = subscription.started_at or now
            subscription.expires_at = expires_at
            subscription.activated_by = activated_by
            subscription.activation_source = activation_source
        user.subscription = subscription
        await self.session.flush()
        if previous_expires_at != expires_at:
            await self.reset_reminders(subscription)
        return subscription

    async def reset_reminders(self, subscription: Subscription) -> None:
        if subscription.id is None:
            return
        await self.session.execute(
            delete(SubscriptionReminder).where(
                SubscriptionReminder.subscription_id == subscription.id
            )
        )

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
