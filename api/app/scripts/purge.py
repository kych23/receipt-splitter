"""Delete expired receipts. Run hourly by the Railway cron service (api/railway.cron.toml).

Usage (from api/): ``uv run python -m app.scripts.purge``
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.logging_config import configure_logging
from app.receipts.purge import purge_expired


def main(database_url: str | None = None) -> int:
    configure_logging()
    url = database_url or get_settings().database_url
    engine = create_engine(url, poolclass=NullPool)
    try:
        with Session(engine) as session:
            return purge_expired(session)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
