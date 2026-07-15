from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(default="")
    database_url: str = "postgresql+asyncpg://teleport:teleport@postgres:5432/teleport"
    admin_ids: str = ""
    log_level: str = "INFO"
    health_host: str = "0.0.0.0"
    health_port: int = 8080
    circle_schedule: str = "каждую неделю в 21:00 НСК в четверг"
    private_chat_id: int | str | None = None
    public_base_url: str | None = None
    webhook_host: str | None = None
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = ""
    yookassa_webhook_path: str = "/webhooks/yookassa"
    yookassa_currency: str = "RUB"
    yookassa_vat_code: int = 1
    yookassa_payment_mode: str = "full_payment"
    yookassa_payment_subject: str = "service"
    subscription_price: Decimal = Decimal("990.00")
    subscription_title: str = "Подписка в Телепорт"
    subscription_description: str = "Доступ в закрытое пространство Телепорт"
    subscription_duration_days: int = 30
    payment_pending_ttl_minutes: int = 60
    payment_reuse_minutes: int = 20
    payment_save_method_enabled: bool = False
    invite_link_ttl_hours: int = 24
    support_url: str | None = None

    @property
    def admin_telegram_ids(self) -> tuple[int, ...]:
        ids: list[int] = []
        for raw in self.admin_ids.split(","):
            raw = raw.strip()
            if raw:
                ids.append(int(raw))
        return tuple(ids)


@lru_cache
def get_settings() -> Settings:
    return Settings()
