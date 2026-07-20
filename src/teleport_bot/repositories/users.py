from datetime import UTC, datetime
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from teleport_bot.models.db import Questionnaire, User
from teleport_bot.models.enums import QuestionnaireStatus


class TelegramUserLike(Protocol):
    @property
    def id(self) -> int: ...

    @property
    def username(self) -> str | None: ...

    @property
    def first_name(self) -> str: ...

    @property
    def last_name(self) -> str | None: ...

    @property
    def language_code(self) -> str | None: ...


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return cast(
            User | None,
            await self.session.scalar(
                select(User)
                .options(selectinload(User.questionnaire), selectinload(User.subscription))
                .where(User.telegram_id == telegram_id)
            ),
        )

    async def get_by_telegram_id_for_update(self, telegram_id: int) -> User | None:
        return cast(
            User | None,
            await self.session.scalar(
                select(User)
                .options(selectinload(User.questionnaire), selectinload(User.subscription))
                .where(User.telegram_id == telegram_id)
                .with_for_update()
            ),
        )

    async def get_by_id(self, user_id: int) -> User | None:
        return cast(User | None, await self.session.get(User, user_id))

    async def set_email(self, user: User, email: str) -> None:
        user.email = email
        await self.session.flush()

    async def all_telegram_ids(self) -> list[int]:
        result = await self.session.scalars(select(User.telegram_id).order_by(User.id))
        return list(result.all())

    async def upsert_from_telegram(self, tg_user: TelegramUserLike) -> tuple[User, bool]:
        if self.session.bind and self.session.bind.dialect.name != "postgresql":
            return await self._upsert_from_telegram_fallback(tg_user)
        now = datetime.now(UTC)
        existed = await self.get_by_telegram_id(tg_user.id) is not None
        values = {
            "telegram_id": tg_user.id,
            "username": tg_user.username,
            "first_name": tg_user.first_name or "",
            "last_name": tg_user.last_name,
            "language_code": tg_user.language_code,
            "first_started_at": now,
            "last_activity_at": now,
        }
        stmt = (
            pg_insert(User)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[User.telegram_id],
                set_={
                    "username": tg_user.username,
                    "first_name": tg_user.first_name or "",
                    "last_name": tg_user.last_name,
                    "language_code": tg_user.language_code,
                    "last_activity_at": now,
                },
            )
            .returning(User.id, User.created_at)
        )
        row = (await self.session.execute(stmt)).one()
        created = not existed
        await self.session.execute(
            pg_insert(Questionnaire)
            .values(
                user_id=row.id,
                status=QuestionnaireStatus.NOT_STARTED.value,
                current_step=0,
            )
            .on_conflict_do_update(
                index_elements=[Questionnaire.user_id],
                set_={"user_id": row.id},
            )
        )
        await self.session.flush()
        user = await self.get_by_telegram_id(tg_user.id)
        if user is None:
            raise RuntimeError("user_upsert_failed")
        return user, created

    async def _upsert_from_telegram_fallback(self, tg_user: TelegramUserLike) -> tuple[User, bool]:
        user = await self.get_by_telegram_id(tg_user.id)
        created = user is None
        now = datetime.now(UTC)
        if user is None:
            user = User(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name or "",
                last_name=tg_user.last_name,
                language_code=tg_user.language_code,
                first_started_at=now,
                last_activity_at=now,
            )
            self.session.add(user)
            await self.session.flush()
        else:
            user.username = tg_user.username
            user.first_name = tg_user.first_name or ""
            user.last_name = tg_user.last_name
            user.language_code = tg_user.language_code
            user.last_activity_at = now
        questionnaire = await self.session.scalar(
            select(Questionnaire).where(Questionnaire.user_id == user.id)
        )
        if questionnaire is None:
            questionnaire = Questionnaire(
                user_id=user.id,
                status=QuestionnaireStatus.NOT_STARTED.value,
                current_step=0,
            )
            self.session.add(questionnaire)
        user.questionnaire = questionnaire
        await self.session.flush()
        return user, created
