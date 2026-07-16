from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from teleport_bot.db.base import Base
from teleport_bot.models.db import Payment, Questionnaire, ReferralAttribution, User
from teleport_bot.models.enums import PaymentStatus, QuestionnaireStatus
from teleport_bot.services.referrals import ReferralService, partner_link


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def session(session_factory: Any) -> Any:
    async with session_factory() as session, session.begin():
        yield session


async def user(session: AsyncSession, tid: int) -> User:
    u = User(
        telegram_id=tid,
        first_name=f"U{tid}",
        first_started_at=datetime.now(UTC),
        last_activity_at=datetime.now(UTC),
    )
    session.add(u)
    await session.flush()
    q = Questionnaire(user_id=u.id, status=QuestionnaireStatus.NOT_STARTED.value, current_step=0)
    session.add(q)
    await session.flush()
    u.questionnaire = q
    return u


async def test_admin_creates_partner_and_unique_link(session: AsyncSession) -> None:
    p = await ReferralService(session).create_partner(
        telegram_id=10, display_name="Partner", created_by_admin_id=1
    )
    assert p.referral_code and len(p.referral_code) >= 16
    bot = SimpleNamespace(get_me=lambda: None)

    async def get_me() -> Any:
        return SimpleNamespace(username="TeleportBot")

    bot.get_me = get_me
    assert await partner_link(bot, p) == f"https://t.me/TeleportBot?start=ref_{p.referral_code}"


async def test_start_valid_invalid_inactive_repeat_other_and_self(session: AsyncSession) -> None:
    svc = ReferralService(session)
    p = await svc.create_partner(telegram_id=10, display_name="P", created_by_admin_id=1)
    u = await user(session, 20)
    assert await svc.attribute_start(u, f"ref_{p.referral_code}", existing_user=False)
    assert await svc.attribute_start(u, "bad", existing_user=False) is None
    assert len((await session.scalars(select(ReferralAttribution))).all()) == 1
    p2 = await svc.create_partner(telegram_id=11, display_name="P2", created_by_admin_id=1)
    await svc.attribute_start(u, f"ref_{p2.referral_code}", existing_user=False)
    attr = await session.scalar(
        select(ReferralAttribution).where(ReferralAttribution.referred_user_id == u.id)
    )
    assert attr is not None
    assert attr.partner_id == p.id
    self_user = await user(session, 10)
    await svc.attribute_start(self_user, f"ref_{p.referral_code}", existing_user=False)
    assert (
        await session.scalar(
            select(ReferralAttribution).where(ReferralAttribution.referred_user_id == self_user.id)
        )
        is None
    )
    p2.status = "inactive"
    u2 = await user(session, 30)
    await svc.attribute_start(u2, f"ref_{p2.referral_code}", existing_user=False)
    assert (
        await session.scalar(
            select(ReferralAttribution).where(ReferralAttribution.referred_user_id == u2.id)
        )
        is None
    )


async def test_funnel_stages_once_and_stats(session: AsyncSession) -> None:
    svc = ReferralService(session)
    p = await svc.create_partner(telegram_id=10, display_name="P", created_by_admin_id=1)
    u = await user(session, 20)
    await svc.attribute_start(u, f"ref_{p.referral_code}", existing_user=False)
    await svc.mark_questionnaire_completed(u)
    await svc.mark_questionnaire_completed(u)
    await svc.mark_payment_link_created(u)
    await svc.mark_payment_link_created(u)
    pay1 = Payment(
        user_id=u.id,
        provider="yookassa",
        provider_payment_id="1",
        idempotency_key="k1",
        status=PaymentStatus.SUCCEEDED.value,
        amount=1,
        currency="RUB",
        paid_at=datetime.now(UTC),
    )
    pay2 = Payment(
        user_id=u.id,
        provider="yookassa",
        provider_payment_id="2",
        idempotency_key="k2",
        status=PaymentStatus.SUCCEEDED.value,
        amount=1,
        currency="RUB",
        paid_at=datetime.now(UTC),
        is_recurring=True,
    )
    session.add_all([pay1, pay2])
    await session.flush()
    await svc.mark_first_payment_succeeded(u, pay1)
    await svc.mark_first_payment_succeeded(u, pay2)
    attr = await session.scalar(select(ReferralAttribution))
    assert attr is not None
    assert attr.first_payment_id == pay1.id
    stats = await svc.stats(p.id)
    assert (stats.starts, stats.questionnaires, stats.payment_links, stats.first_payments) == (
        1,
        1,
        1,
        1,
    )


async def test_manual_assign_forbids_duplicate(session: AsyncSession) -> None:
    svc = ReferralService(session)
    p = await svc.create_partner(telegram_id=10, display_name="P", created_by_admin_id=1)
    u = await user(session, 20)
    await svc.manually_assign(user=u, partner=p, admin_id=1)
    with pytest.raises(ValueError):
        await svc.manually_assign(user=u, partner=p, admin_id=1)
