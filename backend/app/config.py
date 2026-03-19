from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
LEGACY_DATA_DIR = BASE_DIR / "data"
LEGACY_DB_PATH = LEGACY_DATA_DIR / "ashare_ai_trader.db"
APP_HOME_DIR = Path.home() / ".ashare-ai-trader"
DEFAULT_DB_PATH = APP_HOME_DIR / "ashare_ai_trader.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASHARE_", env_file=".env", extra="ignore")

    app_name: str = "A-share AI Trader Backend"
    host: str = "0.0.0.0"
    port: int = 3001
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH}"
    bootstrap_demo_data: bool = True
    default_user_id: str = "test"
    default_user_name: str = "Test User"
    initial_cash: float = 500000.0
    quote_poll_seconds: float = 1.0
    quote_timeout_seconds: float = 5.0
    engine_enabled: bool = True
    market_now_override: str | None = None


settings = Settings()
