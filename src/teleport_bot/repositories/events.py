from hashlib import sha256
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.models.db import EventLog, User
from teleport_bot.models.enums import EventType


def safe_log_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    safe = dict(payload)
    for key in ("link", "invite_link", "url"):
        value = safe.pop(key, None)
        if isinstance(value, str):
            safe[f"{key}_sha256"] = sha256(value.encode()).hexdigest()
            safe[f"{key}_length"] = len(value)
    return safe


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, event_type: EventType, user: User | None, payload: dict[str, Any] | None = None
    ) -> EventLog:
        event = EventLog(
            user_id=user.id if user else None,
            event_type=event_type.value,
            payload=safe_log_payload(payload),
        )
        self.session.add(event)
        await self.session.flush()
        return event
