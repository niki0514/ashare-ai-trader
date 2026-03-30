from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_importing_db_without_database_url_fails_fast(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("ASHARE_DATABASE_URL", None)
    env["PYTHONPATH"] = str(backend_dir)

    result = subprocess.run(
        [sys.executable, "-c", "import app.db"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "ASHARE_DATABASE_URL is not configured" in (result.stdout + result.stderr)
