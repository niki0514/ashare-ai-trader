from __future__ import annotations

import atexit
import os
from pathlib import Path


TEST_DB_DIR = Path(__file__).resolve().parent / ".tmp"
TEST_DB_PATH = TEST_DB_DIR / "test.sqlite3"
TEST_DB_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("ASHARE_DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
os.environ.setdefault("ASHARE_ENGINE_ENABLED", "false")


@atexit.register
def _cleanup_test_db_dir() -> None:
    TEST_DB_PATH.unlink(missing_ok=True)
