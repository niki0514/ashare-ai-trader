from __future__ import annotations

import atexit
import os
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

import pytest


TEST_DB_DIR = Path(mkdtemp(prefix="ashare-pytest-"))
TEST_DB_PATH = TEST_DB_DIR / "test.sqlite3"

os.environ["ASHARE_DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["ASHARE_ENGINE_ENABLED"] = "false"

import app.models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402
from app.quote_client import TencentQuoteClient  # noqa: E402


if engine.dialect.name != "sqlite":
    raise RuntimeError(
        f"Test suite must use isolated SQLite, got {engine.dialect.name}: {engine.url}"
    )


@pytest.fixture(autouse=True)
def _fresh_test_database() -> None:
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _disable_live_quote_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TencentQuoteClient, "fetch_quotes_sync", lambda self, symbols: [])
    monkeypatch.setattr(
        TencentQuoteClient,
        "fetch_daily_bars_sync",
        lambda self, symbol, *, start_trade_date, end_trade_date: [],
    )


@atexit.register
def _cleanup_test_db_dir() -> None:
    rmtree(TEST_DB_DIR, ignore_errors=True)
