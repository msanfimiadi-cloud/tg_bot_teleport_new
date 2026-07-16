import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from teleport_bot.models.db import Partner, Payment, ReferralAttribution, User
from teleport_bot.models.enums import (
    AttributionSource,
    EventType,
    PartnerStatus,
    PaymentStatus,
    QuestionnaireStatus,
)
from teleport_bot.repositories.events import EventRepository

_REF_RE = re.compile(r"^ref_([A-Za-z0-9_-]{8,64})$")


def generate_referral_code() -> str:
    return secrets.token_urlsafe(18).rstrip("=")


def parse_referral_payload(payload: str | None) -> str | None:
    if not payload:
        return None
    m = _REF_RE.fullmatch(payload.strip())
    return m.group(1) if m else None


async def partner_link(bot: object, partner: Partner) -> str:
    me = await bot.get_me()  # type: ignore[attr-defined]
    username = getattr(me, "username", None)
    if not username:
        raise RuntimeError("bot_username_not_available")
    return f"https://t.me/{username}?start=ref_{partner.referral_code}"


@dataclass(frozen=True)
class PartnerStats:
    starts: int
    questionnaires: int
    payment_links: int
    first_payments: int

    @property
    def start_to_questionnaire(self) -> float:
        return self.questionnaires / self.starts * 100 if self.starts else 0.0

    @property
    def questionnaire_to_payment(self) -> float:
        return self.first_payments / self.questionnaires * 100 if self.questionnaires else 0.0

    @property
    def start_to_payment(self) -> float:
        return self.first_payments / self.starts * 100 if self.starts else 0.0


class ReferralService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.events = EventRepository(session)

    async def create_partner(
        self,
        *,
        telegram_id: int,
        display_name: str,
        created_by_admin_id: int,
        note: str | None = None,
    ) -> Partner:
        user = await self.session.scalar(select(User).where(User.telegram_id == telegram_id))
        for _ in range(5):
            partner = Partner(
                user_id=user.id if user else None,
                telegram_id=telegram_id,
                username=user.username if user else None,
                display_name=display_name,
                referral_code=generate_referral_code(),
                status=PartnerStatus.ACTIVE.value,
                created_by_admin_id=created_by_admin_id,
                note=note,
            )
            self.session.add(partner)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                if await self.get_partner_by_telegram_id(telegram_id):
                    raise ValueError("partner_exists") from None
                continue
            await self.events.add(EventType.PARTNER_CREATED, user, {"partner_id": partner.id})
            return partner
        raise RuntimeError("referral_code_generation_failed")

    async def get_partner_by_telegram_id(self, telegram_id: int) -> Partner | None:
        return cast(
            Partner | None,
            await self.session.scalar(select(Partner).where(Partner.telegram_id == telegram_id)),
        )

    async def link_partner_user(self, user: User) -> None:
        partner = await self.get_partner_by_telegram_id(user.telegram_id)
        if partner and partner.user_id is None:
            partner.user_id = user.id
            partner.username = user.username
            await self.session.flush()

    async def attribute_start(
        self, user: User, payload: str | None, *, existing_user: bool
    ) -> ReferralAttribution | None:
        code = parse_referral_payload(payload)
        if not code:
            if payload:
                await self._skip(user, "invalid_code")
            return None
        existing = await self.session.scalar(
            select(ReferralAttribution).where(ReferralAttribution.referred_user_id == user.id)
        )
        if existing:
            await self._skip(user, "attribution_exists", code)
            return existing
        partner = await self.session.scalar(select(Partner).where(Partner.referral_code == code))
        if partner is None:
            await self._skip(user, "partner_not_found", code)
            return None
        if partner.status != PartnerStatus.ACTIVE.value:
            await self._skip(user, "partner_inactive", code, partner.id)
            return None
        if partner.telegram_id == user.telegram_id:
            await self._skip(user, "self_referral", code, partner.id)
            return None
        if existing_user and not await self._existing_user_is_eligible(user):
            await self._skip(user, "existing_user_ineligible", code, partner.id)
            return None
        attr = ReferralAttribution(
            referred_user_id=user.id,
            partner_id=partner.id,
            referral_code_used=code,
            first_start_at=datetime.now(UTC),
            attribution_source=AttributionSource.DEEP_LINK.value,
        )
        self.session.add(attr)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return cast(
                ReferralAttribution | None,
                await self.session.scalar(
                    select(ReferralAttribution).where(
                        ReferralAttribution.referred_user_id == user.id
                    )
                ),
            )
        await self.events.add(
            EventType.REFERRAL_ATTRIBUTED, user, {"partner_id": partner.id, "code_hash": hash(code)}
        )
        return attr

    async def _existing_user_is_eligible(self, user: User) -> bool:
        if user.questionnaire and user.questionnaire.status == QuestionnaireStatus.COMPLETED.value:
            return False
        paid = await self.session.scalar(
            select(Payment.id)
            .where(Payment.user_id == user.id, Payment.status == PaymentStatus.SUCCEEDED.value)
            .limit(1)
        )
        return paid is None

    async def _skip(
        self, user: User, reason: str, code: str | None = None, partner_id: int | None = None
    ) -> None:
        await self.events.add(
            EventType.REFERRAL_ATTRIBUTION_SKIPPED,
            user,
            {"reason": reason, "partner_id": partner_id, "code_hash": hash(code) if code else None},
        )

    async def mark_questionnaire_completed(self, user: User) -> None:
        attr = await self._attr(user.id)
        if attr and attr.questionnaire_completed_at is None:
            attr.questionnaire_completed_at = datetime.now(UTC)
            await self.events.add(
                EventType.REFERRAL_QUESTIONNAIRE_COMPLETED, user, {"partner_id": attr.partner_id}
            )

    async def mark_payment_link_created(self, user: User) -> None:
        attr = await self._attr(user.id)
        if attr and attr.payment_link_created_at is None:
            attr.payment_link_created_at = datetime.now(UTC)
            await self.events.add(
                EventType.REFERRAL_PAYMENT_LINK_CREATED, user, {"partner_id": attr.partner_id}
            )

    async def mark_first_payment_succeeded(self, user: User, payment: Payment) -> None:
        attr = await self._attr(user.id)
        if attr and attr.first_payment_succeeded_at is None:
            attr.first_payment_succeeded_at = payment.paid_at or datetime.now(UTC)
            attr.first_payment_id = payment.id
            await self.events.add(
                EventType.REFERRAL_FIRST_PAYMENT_SUCCEEDED,
                user,
                {"partner_id": attr.partner_id, "payment_id": payment.id},
            )

    async def manually_assign(
        self, *, user: User, partner: Partner, admin_id: int
    ) -> ReferralAttribution:
        if await self._attr(user.id):
            raise ValueError("attribution_exists")
        first_payment = await self.session.scalar(
            select(Payment)
            .where(Payment.user_id == user.id, Payment.status == PaymentStatus.SUCCEEDED.value)
            .order_by(Payment.paid_at.asc().nullslast(), Payment.created_at.asc())
            .limit(1)
        )
        attr = ReferralAttribution(
            referred_user_id=user.id,
            partner_id=partner.id,
            referral_code_used=partner.referral_code,
            first_start_at=user.created_at,
            created_by_admin_id=admin_id,
            attribution_source=AttributionSource.MANUAL.value,
            questionnaire_completed_at=(
                user.questionnaire.completed_at
                if user.questionnaire
                and user.questionnaire.status == QuestionnaireStatus.COMPLETED.value
                else None
            ),
            first_payment_succeeded_at=(first_payment.paid_at if first_payment else None),
            first_payment_id=(first_payment.id if first_payment else None),
        )
        self.session.add(attr)
        await self.session.flush()
        await self.events.add(
            EventType.REFERRAL_MANUALLY_ASSIGNED,
            user,
            {"partner_id": partner.id, "admin_id": admin_id},
        )
        return attr

    async def stats(self, partner_id: int | None = None, days: int | None = None) -> PartnerStats:
        start = datetime.now(UTC) - timedelta(days=days) if days else None
        base = select(ReferralAttribution)
        if partner_id is not None:
            base = base.where(ReferralAttribution.partner_id == partner_id)

        async def count(col: Any) -> int:
            stmt = select(func.count(ReferralAttribution.id))
            if partner_id is not None:
                stmt = stmt.where(ReferralAttribution.partner_id == partner_id)
            stmt = stmt.where(col.is_not(None))
            if start:
                stmt = stmt.where(col >= start)
            return int(await self.session.scalar(stmt) or 0)

        return PartnerStats(
            await count(ReferralAttribution.first_start_at),
            await count(ReferralAttribution.questionnaire_completed_at),
            await count(ReferralAttribution.payment_link_created_at),
            await count(ReferralAttribution.first_payment_succeeded_at),
        )

    async def _attr(self, user_id: int) -> ReferralAttribution | None:
        return cast(
            ReferralAttribution | None,
            await self.session.scalar(
                select(ReferralAttribution)
                .where(ReferralAttribution.referred_user_id == user_id)
                .options(selectinload(ReferralAttribution.partner))
            ),
        )
