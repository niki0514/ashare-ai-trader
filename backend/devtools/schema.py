from __future__ import annotations

import argparse
from collections.abc import Iterable

import app.models  # noqa: F401
from app.db import Base, engine
from sqlalchemy import inspect


def _expected_tables() -> set[str]:
    return set(Base.metadata.tables.keys())


def _existing_tables() -> set[str]:
    return set(inspect(engine).get_table_names())


def _business_tables(existing_tables: Iterable[str]) -> set[str]:
    return set(existing_tables) & _expected_tables()


def init_db() -> str:
    expected_tables = _expected_tables()
    existing_tables = _existing_tables()
    existing_business_tables = _business_tables(existing_tables)

    if not existing_business_tables:
        Base.metadata.create_all(bind=engine)
        return "created"

    if existing_business_tables == expected_tables:
        return "ready"

    missing_tables = sorted(expected_tables - existing_business_tables)
    present_tables = sorted(existing_business_tables)
    raise RuntimeError(
        "Database schema is partially initialized; refusing to auto-complete it. "
        f"Present business tables: {present_tables}. Missing business tables: {missing_tables}."
    )


def reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def schema_status() -> dict[str, list[str] | str]:
    expected_tables = sorted(_expected_tables())
    existing_tables = sorted(_existing_tables())
    existing_business_tables = sorted(_business_tables(existing_tables))

    if not existing_business_tables:
        state = "empty"
    elif set(existing_business_tables) == set(expected_tables):
        state = "ready"
    else:
        state = "partial"

    return {
        "state": state,
        "expected": expected_tables,
        "existing": existing_tables,
        "business": existing_business_tables,
        "missing": sorted(set(expected_tables) - set(existing_business_tables)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Database schema helper")
    parser.add_argument("command", choices=["init", "status"])
    args = parser.parse_args()

    if args.command == "init":
        print(init_db())
        return

    print(schema_status())


if __name__ == "__main__":
    main()
