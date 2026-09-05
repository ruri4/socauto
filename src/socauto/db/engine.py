"""SQLite engine and session configuration."""

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import URL, Engine, event
from sqlmodel import Session, create_engine

from socauto.config import Settings, get_settings


def database_url(settings: Settings) -> URL:
    return URL.create(
        drivername="sqlite+pysqlite",
        database=str(settings.database_path.resolve()),
    )


def _configure_sqlite(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def create_db_engine(settings: Settings) -> Engine:
    settings.prepare_runtime()
    engine = create_engine(
        database_url(settings),
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    event.listen(engine, "connect", _configure_sqlite)
    return engine


@lru_cache
def get_engine() -> Engine:
    return create_db_engine(get_settings())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
