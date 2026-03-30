from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import Base, engine
from devtools.schema import init_db, schema_status


def test_init_db_creates_tables_for_empty_database() -> None:
    Base.metadata.drop_all(bind=engine)

    assert schema_status()["state"] == "empty"
    assert init_db() == "created"
    assert schema_status()["state"] == "ready"


def test_init_db_rejects_partial_business_schema() -> None:
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


def test_init_db_rejects_incompatible_legacy_schema() -> None:
    assert init_db() == "ready"

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE position_lots"))
        connection.execute(
            text(
                """
                CREATE TABLE position_lots (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) REFERENCES users(id) ON DELETE CASCADE,
                    symbol VARCHAR(16) NOT NULL,
                    symbol_name VARCHAR(255),
                    opened_order_id VARCHAR(64),
                    opened_trade_id VARCHAR(64),
                    opened_date VARCHAR(10) NOT NULL,
                    opened_at DATETIME NOT NULL,
                    cost_price FLOAT NOT NULL,
                    original_shares INTEGER NOT NULL,
                    remaining_shares INTEGER NOT NULL,
                    sellable_shares INTEGER NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    closed_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_position_lots_user_symbol_status "
                "ON position_lots(user_id, symbol, status)"
            )
        )

    status = schema_status()
    assert status["state"] == "incompatible"
    assert "position_lots.opened_order_id must be NOT NULL" in status["issues"]
    assert (
        "position_lots.opened_trade_id must reference execution_trades.id"
        in status["issues"]
    )

    with pytest.raises(RuntimeError, match="incompatible with the current application contract"):
        init_db()
