from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

from app.config import settings
from app.db import engine


def _masked_database_url() -> str:
    url = settings.database_url
    if engine.dialect.name == "sqlite":
        return url

    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"

    if parsed.username:
        credentials = parsed.username
        if parsed.password:
            credentials = f"{credentials}:***"
        hostname = f"{credentials}@{hostname}"

    return urlunsplit((parsed.scheme, hostname, parsed.path, parsed.query, parsed.fragment))


def require_postgres_confirmation(
    *,
    action: str,
    confirm_env: str,
    expected_value: str = "1",
) -> None:
    if engine.dialect.name != "postgresql":
        return

    if os.getenv(confirm_env) == expected_value:
        return

    raise SystemExit(
        "\n".join(
            [
                f"Refusing to run `{action}` against PostgreSQL without explicit confirmation.",
                f"Target database: {_masked_database_url()}",
                "Make sure you no longer need the current PostgreSQL data before continuing.",
                f"Then retry with: `{confirm_env}={expected_value}`",
            ]
        )
    )
