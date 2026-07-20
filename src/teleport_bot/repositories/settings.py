from decimal import Decimal
from urllib.parse import urlparse

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


def normalize_setting(key: str, value: str) -> str:
    value = value.strip()
    if key == "subscription_price":
        try:
            price = Decimal(value)
        except Exception as exc:
            raise ValueError("invalid_subscription_price") from exc
        if not price.is_finite() or price <= 0 or price > Decimal("99999999.99"):
            raise ValueError("invalid_subscription_price")
        return f"{price:.2f}"
    if key == "subscription_duration_days":
        try:
            days = int(value)
        except ValueError as exc:
            raise ValueError("invalid_subscription_duration_days") from exc
        if not 1 <= days <= 3650:
            raise ValueError("invalid_subscription_duration_days")
        return str(days)
    if key == "circle_schedule":
        if not value or len(value) > 500:
            raise ValueError("invalid_circle_schedule")
        return value
    if key == "support_url":
        if value in {"", "-"}:
            return ""
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(value) > 2048:
            raise ValueError("invalid_support_url")
        return value
    raise ValueError("setting_not_allowed")


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> str | None:
        row = await self.session.get(AppSetting, key)
        return row.value if row else None

    async def set(self, key: str, value: str, admin_id: int) -> AppSetting:
        if key not in ALLOWED_SETTINGS:
            raise ValueError("setting_not_allowed")
        value = normalize_setting(key, value)
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
            try:
                value = normalize_setting(key, value)
            except ValueError:
                continue
            if key == "subscription_price":
                values[key] = Decimal(value)
            elif key == "subscription_duration_days":
                values[key] = int(value)
            else:
                values[key] = value
        return values

    async def resolved(self, settings: Settings) -> Settings:
        values = await self.effective(settings)
        if values["support_url"] == "":
            values["support_url"] = None
        return Settings.model_validate({**settings.model_dump(), **values})
