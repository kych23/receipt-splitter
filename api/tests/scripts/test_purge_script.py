from uuid import UUID

import pytest
from sqlalchemy import Engine, delete, select, text

from app.db.models import Receipt
from app.scripts.purge import main

pytestmark = pytest.mark.db


def test_purge_script_deletes_only_expired_rows(
    migrated_engine: Engine, test_database_url: str
) -> None:
    # Committed on a separate connection: the script opens its own engine and cannot see
    # the rolled-back db_session transaction.
    with migrated_engine.begin() as conn:
        expired_id: UUID = conn.execute(
            text(
                "INSERT INTO receipts (expires_at) "
                "VALUES (clock_timestamp() - interval '1 minute') RETURNING id"
            )
        ).scalar_one()
        live_id: UUID = conn.execute(
            text("INSERT INTO receipts DEFAULT VALUES RETURNING id")
        ).scalar_one()
    try:
        assert main(test_database_url) == 1
        with migrated_engine.connect() as conn:
            remaining = set(
                conn.scalars(select(Receipt.id).where(Receipt.id.in_([expired_id, live_id])))
            )
        assert remaining == {live_id}
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(delete(Receipt).where(Receipt.id.in_([expired_id, live_id])))
