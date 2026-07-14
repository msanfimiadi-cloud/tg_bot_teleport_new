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
