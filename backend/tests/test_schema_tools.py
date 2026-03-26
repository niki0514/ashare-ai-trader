from __future__ import annotations

from sqlalchemy import text

from app.db import engine
from devtools.schema import init_db, reset_db, schema_status


def test_init_db_creates_tables_for_empty_database() -> None:
    reset_db()

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE import_batch_items"))
        connection.execute(text("DROP TABLE import_batches"))
        connection.execute(text("DROP TABLE order_events"))
        connection.execute(text("DROP TABLE execution_trades"))
        connection.execute(text("DROP TABLE instruction_orders"))
        connection.execute(text("DROP TABLE cash_ledger"))
        connection.execute(text("DROP TABLE daily_pnl_details"))
        connection.execute(text("DROP TABLE daily_pnl"))
        connection.execute(text("DROP TABLE eod_prices"))
        connection.execute(text("DROP TABLE intraday_quotes"))
        connection.execute(text("DROP TABLE position_lots"))
        connection.execute(text("DROP TABLE users"))

    assert schema_status()["state"] == "empty"
    assert init_db() == "created"
    assert schema_status()["state"] == "ready"


def test_init_db_rejects_partial_business_schema() -> None:
    reset_db()

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE import_batch_items"))

    assert schema_status()["state"] == "partial"

    try:
        init_db()
    except RuntimeError as exc:
        assert "partially initialized" in str(exc)
        assert "import_batch_items" in str(exc)
    else:
        raise AssertionError("init_db should reject partial schema")
