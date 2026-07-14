from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.models.db import EventLog, User
from teleport_bot.models.enums import EventType


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, event_type: EventType, user: User | None, payload: dict[str, Any] | None = None
    ) -> EventLog:
        event = EventLog(
            user_id=user.id if user else None, event_type=event_type.value, payload=payload or {}
        )
        self.session.add(event)
        await self.session.flush()
        return event
