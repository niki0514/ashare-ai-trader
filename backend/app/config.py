from __future__ import annotations

import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


DOCKER_POSTGRES_DATABASE_URL = (
    "postgresql+psycopg://ashare:ashare@127.0.0.1:5433/ashare_ai_trader"
)


def _running_under_pytest() -> bool:
    return "pytest" in sys.modules


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASHARE_", env_file=".env", extra="ignore")

    app_name: str = "A-share AI Trader Backend"
    host: str = "0.0.0.0"
    port: int = 3101
    reload: bool = False
    database_url: str | None = None
    quote_poll_seconds: float = 1.0
    quote_timeout_seconds: float = 5.0
    engine_enabled: bool = True
    market_now_override: str | None = None
    market_holiday_dates: str = ""


settings = Settings()


def require_database_url() -> str:
    database_url = (settings.database_url or "").strip()
    if database_url:
        return database_url

    raise RuntimeError(
        "ASHARE_DATABASE_URL is not configured. Pytest sets a temporary SQLite database "
        "automatically. For app/devtools entrypoints, set ASHARE_DATABASE_URL explicitly "
        "or add it to backend/.env. For local Docker PostgreSQL, use: "
        f"{DOCKER_POSTGRES_DATABASE_URL}"
    )


if _running_under_pytest() and not require_database_url().startswith("sqlite"):
    raise RuntimeError(
        "Pytest must run against an isolated SQLite database. "
        f"Got: {require_database_url()}"
    )
