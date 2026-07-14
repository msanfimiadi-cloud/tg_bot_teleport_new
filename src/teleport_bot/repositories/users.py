from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.models.db import Questionnaire, User
from teleport_bot.models.enums import QuestionnaireStatus


class TelegramUserLike(Protocol):
    id: int
    username: str | None
    first_name: str
    last_name: str | None
    language_code: str | None


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.telegram_id == telegram_id))

    async def upsert_from_telegram(self, tg_user: TelegramUserLike) -> tuple[User, bool]:
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
            questionnaire = Questionnaire(
                user_id=user.id,
                status=QuestionnaireStatus.NOT_STARTED.value,
                current_step=0,
            )
            self.session.add(questionnaire)
            await self.session.flush()
            user.questionnaire = questionnaire
        else:
            user.username = tg_user.username
            user.first_name = tg_user.first_name or ""
            user.last_name = tg_user.last_name
            user.language_code = tg_user.language_code
            user.last_activity_at = now
            if user.questionnaire is None:
                user.questionnaire = Questionnaire(user_id=user.id)
                self.session.add(user.questionnaire)
        return user, created
