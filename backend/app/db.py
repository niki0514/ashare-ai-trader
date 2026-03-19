from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import shutil

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DEFAULT_DB_PATH, LEGACY_DB_PATH, settings


class Base(DeclarativeBase):
    pass


def _sqlite_path_from_url(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    raw_path = database_url.removeprefix(prefix)
    if raw_path == ":memory:" or raw_path.startswith("file:"):
        return None
    return Path(raw_path).expanduser()


def _maybe_adopt_legacy_sqlite(database_url: str) -> None:
    sqlite_path = _sqlite_path_from_url(database_url)
    if sqlite_path is None or sqlite_path.exists():
        return
    if sqlite_path != DEFAULT_DB_PATH.expanduser():
        return
    if not LEGACY_DB_PATH.exists():
        return

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_DB_PATH, sqlite_path)


class DatabaseRuntime:
    def __init__(self, database_url: str):
        self.database_url = database_url
        _maybe_adopt_legacy_sqlite(database_url)

        sqlite_path = _sqlite_path_from_url(database_url)
        if sqlite_path is not None:
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(database_url, future=True)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )

    def init_schema(self) -> None:
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


db_runtime = DatabaseRuntime(settings.database_url)
engine = db_runtime.engine
SessionLocal = db_runtime.session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    with db_runtime.session_scope() as session:
        yield session
