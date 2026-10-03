"""Database engine and session dependencies.

Engines are keyed by URL and always derived from the settings the app was created with
(``request.app.state.settings``), never from the process-wide ``DATABASE_URL``, so an app built
for a test database cannot silently talk to another one.
"""

from collections.abc import Callable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config import Settings

DatabaseCheck = Callable[[], None]

READINESS_STATEMENT_TIMEOUT_MS = 2000
_ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"


class SchemaNotCurrent(Exception):
    """The database is reachable but not migrated to this code's Alembic head."""


@lru_cache(maxsize=1)
def migration_revisions() -> tuple[str, frozenset[str]]:
    """This code's Alembic head and every revision it knows (read once from api/alembic)."""
    config = Config()
    config.set_main_option("script_location", str(_ALEMBIC_DIR))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("no Alembic head found")
    return head, frozenset(rev.revision for rev in script.walk_revisions())


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
    """Raise if the database is unreachable (``SQLAlchemyError``) or not migrated to this code's
    head (``SchemaNotCurrent``; a missing ``alembic_version`` table raises ``SQLAlchemyError``).

    A revision this code doesn't know counts as ready: Railway runs a new release's migrations while
    the old container still serves, and expand → contract keeps the old code compatible with them.
    The statement timeout is scoped to this transaction so it never affects other queries.
    """
    head, known = migration_revisions()
    with engine.begin() as connection:
        connection.execute(text(f"SET LOCAL statement_timeout = {READINESS_STATEMENT_TIMEOUT_MS}"))
        versions = set(connection.scalars(text("SELECT version_num FROM alembic_version")))
    if head in versions:
        return
    if not versions or versions <= known:
        raise SchemaNotCurrent(f"database at {sorted(versions) or 'no revision'}, code at {head}")


def get_database_check(engine: Annotated[Engine, Depends(get_engine)]) -> DatabaseCheck:
    return lambda: check_database(engine)
