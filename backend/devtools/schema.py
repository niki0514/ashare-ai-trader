from __future__ import annotations

import argparse
from collections.abc import Iterable
import re

import app.models  # noqa: F401
from app.db import Base, engine
from sqlalchemy import inspect


def _expected_tables() -> set[str]:
    return set(Base.metadata.tables.keys())


def _existing_tables() -> set[str]:
    return set(inspect(engine).get_table_names())


def _business_tables(existing_tables: Iterable[str]) -> set[str]:
    return set(existing_tables) & _expected_tables()


def _normalize_check_sql(sqltext: str | None) -> str:
    if not sqltext:
        return ""
    return re.sub(r"[\s\"'`]+", "", sqltext.lower())


def _column_is_non_nullable(table: str, column: str) -> bool:
    inspector = inspect(engine)
    columns = {
        column_info["name"]: column_info for column_info in inspector.get_columns(table)
    }
    column_info = columns.get(column)
    return bool(column_info) and not bool(column_info["nullable"])


def _has_foreign_key(
    table: str,
    constrained_columns: list[str],
    referred_table: str,
    referred_columns: list[str],
) -> bool:
    inspector = inspect(engine)
    for foreign_key in inspector.get_foreign_keys(table):
        if foreign_key.get("referred_table") != referred_table:
            continue
        if foreign_key.get("constrained_columns") != constrained_columns:
            continue
        if foreign_key.get("referred_columns") != referred_columns:
            continue
        return True
    return False


def _has_check_constraint(
    table: str,
    required_token_sets: list[list[str]],
) -> bool:
    inspector = inspect(engine)
    constraints = [
        _normalize_check_sql(constraint.get("sqltext"))
        for constraint in inspector.get_check_constraints(table)
    ]
    for token_set in required_token_sets:
        if any(all(token in constraint for token in token_set) for constraint in constraints):
            return True
    return False


def _schema_contract_issues(existing_business_tables: set[str]) -> list[str]:
    if existing_business_tables != _expected_tables():
        return []

    issues: list[str] = []

    if not _column_is_non_nullable("position_lots", "opened_order_id"):
        issues.append("position_lots.opened_order_id must be NOT NULL")
    if not _column_is_non_nullable("position_lots", "opened_trade_id"):
        issues.append("position_lots.opened_trade_id must be NOT NULL")
    if not _has_foreign_key(
        "position_lots",
        ["opened_order_id"],
        "instruction_orders",
        ["id"],
    ):
        issues.append("position_lots.opened_order_id must reference instruction_orders.id")
    if not _has_foreign_key(
        "position_lots",
        ["opened_trade_id"],
        "execution_trades",
        ["id"],
    ):
        issues.append("position_lots.opened_trade_id must reference execution_trades.id")
    if not _has_check_constraint(
        "position_lots",
        [["original_shares", ">0"]],
    ):
        issues.append("position_lots must enforce original_shares > 0")
    if not _has_check_constraint(
        "position_lots",
        [
            ["remaining_shares", ">=0", "<=original_shares"],
            ["remaining_shares", ">=0", "original_shares>=remaining_shares"],
        ],
    ):
        issues.append(
            "position_lots must enforce 0 <= remaining_shares <= original_shares"
        )
    if not _has_check_constraint(
        "position_lots",
        [
            ["sellable_shares", ">=0", "<=remaining_shares"],
            ["sellable_shares", ">=0", "remaining_shares>=sellable_shares"],
        ],
    ):
        issues.append(
            "position_lots must enforce 0 <= sellable_shares <= remaining_shares"
        )

    if not _has_foreign_key(
        "cash_ledger",
        ["reference_id"],
        "execution_trades",
        ["id"],
    ):
        issues.append("cash_ledger.reference_id must reference execution_trades.id")
    if not _has_check_constraint(
        "cash_ledger",
        [
            [
                "entry_type",
                "buy",
                "sell",
                "reference_type",
                "executiontrade",
                "reference_idisnotnull",
            ]
        ],
    ):
        issues.append(
            "cash_ledger must require BUY/SELL rows to reference ExecutionTrade"
        )
    if not _has_check_constraint(
        "cash_ledger",
        [
            [
                "reference_idisnull",
                "entry_type",
                "buy",
                "sell",
                "reference_type",
                "executiontrade",
            ]
        ],
    ):
        issues.append(
            "cash_ledger must forbid non-trade rows from carrying reference_id"
        )

    return issues


def init_db() -> str:
    expected_tables = _expected_tables()
    existing_tables = _existing_tables()
    existing_business_tables = _business_tables(existing_tables)

    if not existing_business_tables:
        Base.metadata.create_all(bind=engine)
        return "created"

    if existing_business_tables == expected_tables:
        issues = _schema_contract_issues(existing_business_tables)
        if not issues:
            return "ready"
        raise RuntimeError(
            "Database schema is incompatible with the current application contract; "
            f"refusing to run. Issues: {issues}."
        )

    missing_tables = sorted(expected_tables - existing_business_tables)
    present_tables = sorted(existing_business_tables)
    raise RuntimeError(
        "Database schema is partially initialized; refusing to auto-complete it. "
        f"Present business tables: {present_tables}. Missing business tables: {missing_tables}."
    )


def schema_status() -> dict[str, list[str] | str]:
    expected_tables = sorted(_expected_tables())
    existing_tables = sorted(_existing_tables())
    existing_business_tables = sorted(_business_tables(existing_tables))
    issues = _schema_contract_issues(set(existing_business_tables))

    if not existing_business_tables:
        state = "empty"
    elif issues:
        state = "incompatible"
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
        "issues": issues,
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
