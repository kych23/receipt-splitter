"""Deletes receipts past their expiry (docs/design/slice-3-manual-split.md, "Data lifecycle")."""

import logging

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.db.models import Receipt

logger = logging.getLogger(__name__)


def purge_expired(session: Session) -> int:
    """Delete expired receipts (cascading to their parse attempts and corrections) and commit.

    Returns the number of receipts deleted. Logs only the count, never receipt contents.
    """
    result = session.execute(delete(Receipt).where(Receipt.expires_at <= func.clock_timestamp()))
    session.commit()
    count = int(getattr(result, "rowcount", 0) or 0)
    logger.info("purged %d expired receipts", count)
    return count
