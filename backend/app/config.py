from __future__ import annotations

import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_DATABASE_URL = "postgresql+psycopg://ashare:ashare@127.0.0.1:5433/ashare_ai_trader"


def _running_under_pytest() -> bool:
    return "pytest" in sys.modules


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASHARE_", env_file=".env", extra="ignore")

    app_name: str = "A-share AI Trader Backend"
    host: str = "0.0.0.0"
    port: int = 3101
    reload: bool = False
    database_url: str = DEFAULT_DATABASE_URL
    quote_poll_seconds: float = 1.0
    quote_timeout_seconds: float = 5.0
    engine_enabled: bool = True
    market_now_override: str | None = None
    market_holiday_dates: str = ""


settings = Settings()


if _running_under_pytest() and not settings.database_url.startswith("sqlite"):
    raise RuntimeError(
        "Pytest must run against an isolated SQLite database. "
        f"Got: {settings.database_url}"
    )
