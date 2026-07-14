from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from teleport_bot.config.settings import Settings
from teleport_bot.models.db import AppSetting
from teleport_bot.models.enums import EventType
from teleport_bot.repositories.events import EventRepository

ALLOWED_SETTINGS = {
    "subscription_price",
    "subscription_duration_days",
    "circle_schedule",
    "support_url",
}


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> str | None:
        row = await self.session.get(AppSetting, key)
        return row.value if row else None

    async def set(self, key: str, value: str, admin_id: int) -> AppSetting:
        if key not in ALLOWED_SETTINGS:
            raise ValueError("setting_not_allowed")
        row = await self.session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=value, updated_by=admin_id)
            self.session.add(row)
        else:
            row.value = value
            row.updated_by = admin_id
        await EventRepository(self.session).add(
            EventType.SETTINGS_CHANGED, None, {"key": key, "value": value, "admin_id": admin_id}
        )
        await self.session.flush()
        return row

    async def effective(self, settings: Settings) -> dict[str, object]:
        values: dict[str, object] = {
            "subscription_price": settings.subscription_price,
            "subscription_duration_days": settings.subscription_duration_days,
            "circle_schedule": settings.circle_schedule,
            "support_url": settings.support_url,
        }
        for key in ALLOWED_SETTINGS:
            value = await self.get(key)
            if value is None:
                continue
            if key == "subscription_price":
                values[key] = Decimal(value)
            elif key == "subscription_duration_days":
                values[key] = int(value)
            else:
                values[key] = value
        return values
