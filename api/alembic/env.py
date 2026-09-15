"""Alembic environment. Online migrations only.

The database URL comes from ``config.attributes["connection_url"]`` when set (tests point this at
the test database) and otherwise from app settings (``DATABASE_URL``).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

import app.db.models  # noqa: F401  (registers all tables on Base.metadata)
from app.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = config.attributes.get("connection_url") or get_settings().database_url
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline migrations not supported")

run_migrations_online()
