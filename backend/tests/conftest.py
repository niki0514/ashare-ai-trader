from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path


TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="ashare-ai-trader-tests-"))
TEST_DB_PATH = TEST_DB_DIR / "test.sqlite3"

os.environ.setdefault("ASHARE_DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
os.environ.setdefault("ASHARE_ENGINE_ENABLED", "false")


@atexit.register
def _cleanup_test_db_dir() -> None:
    shutil.rmtree(TEST_DB_DIR, ignore_errors=True)
