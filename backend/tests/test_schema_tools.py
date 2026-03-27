from __future__ import annotations

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
