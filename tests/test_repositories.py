from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from teleport_bot.db.base import Base
from teleport_bot.models.db import EventLog
from teleport_bot.models.enums import EventType, QuestionnaireStatus
from teleport_bot.repositories.events import EventRepository
from teleport_bot.repositories.users import UserRepository


@dataclass
class TgUser:
    id: int
    username: str | None
    first_name: str
    last_name: str | None = None
    language_code: str | None = None


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_new_user_start_and_repeat_during_questionnaire(session_factory) -> None:
    async with session_factory() as session, session.begin():
        repo = UserRepository(session)
        user, created = await repo.upsert_from_telegram(TgUser(1, None, "A"))
        user.questionnaire.status = QuestionnaireStatus.IN_PROGRESS.value
        user.questionnaire.current_step = 2
        again, created_again = await repo.upsert_from_telegram(TgUser(1, "name", "A"))
        assert created is True
        assert created_again is False
        assert again.questionnaire.current_step == 2


async def test_repeat_start_after_completed(session_factory) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(2, None, "B"))
        user.questionnaire.status = QuestionnaireStatus.COMPLETED.value
        await session.flush()
        loaded = await UserRepository(session).get_by_telegram_id(2)
        assert loaded is not None
        assert loaded.questionnaire.status == QuestionnaireStatus.COMPLETED.value


async def test_admin_notification_error_event_does_not_break(session_factory) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(3, None, "C"))
        await EventRepository(session).add(
            EventType.ADMIN_NOTIFICATION_FAILED, user, {"error": "X"}
        )
        rows = (await session.scalars(select(EventLog))).all()
        assert rows[0].event_type == EventType.ADMIN_NOTIFICATION_FAILED.value


async def test_payment_stage_event_saved(session_factory) -> None:
    async with session_factory() as session, session.begin():
        user, _ = await UserRepository(session).upsert_from_telegram(TgUser(4, None, "D"))
        await EventRepository(session).add(EventType.PAYMENT_STAGE_REACHED, user)
        rows = (await session.scalars(select(EventLog))).all()
        assert rows[0].event_type == EventType.PAYMENT_STAGE_REACHED.value
