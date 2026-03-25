from __future__ import annotations

from sqlalchemy import text

from .db import engine, init_schema


def _ensure_order_status_values() -> None:
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'cancelled'"))


def bootstrap_database() -> None:
    init_schema()
    _ensure_order_status_values()


def main() -> None:
    bootstrap_database()


if __name__ == "__main__":
    main()
