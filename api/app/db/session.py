"""Database engine and session dependencies.

Engines are keyed by URL and always derived from the settings the app was created with
(``request.app.state.settings``), never from the process-wide ``DATABASE_URL``, so an app built
for a test database cannot silently talk to another one.
"""

from collections.abc import Callable, Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config import Settings

DatabaseCheck = Callable[[], None]

READINESS_STATEMENT_TIMEOUT_MS = 2000


@lru_cache(maxsize=4)
def engine_for(database_url: str) -> Engine:
    # Creating an engine never connects; connections are opened lazily on first use.
    # pool_timeout bounds waiting for a pooled connection (not query time), so /readyz returns 503
    # within seconds even when the pool is exhausted.
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_timeout=2,
        connect_args={"connect_timeout": 2},
    )


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(settings: Annotated[Settings, Depends(get_app_settings)]) -> Engine:
    return engine_for(settings.database_url)


def get_session(engine: Annotated[Engine, Depends(get_engine)]) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


def check_database(engine: Engine) -> None:
    """Raise ``SQLAlchemyError`` if the database is unreachable or unresponsive.

    The statement timeout is scoped to this transaction so it never affects other queries.
    """
    with engine.begin() as connection:
        connection.execute(text(f"SET LOCAL statement_timeout = {READINESS_STATEMENT_TIMEOUT_MS}"))
        connection.execute(text("SELECT 1"))


def get_database_check(engine: Annotated[Engine, Depends(get_engine)]) -> DatabaseCheck:
    return lambda: check_database(engine)
