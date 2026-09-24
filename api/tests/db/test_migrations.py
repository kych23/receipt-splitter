import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text

import app.db.models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base

pytestmark = pytest.mark.db

# No deferred FKs remain after 0002 (they existed only for household cascades).
DEFERRED_FKS: set[str] = set()

# Every constraint in the public schema at head, by name -> pg_constraint.contype.
# (Slice 3 design doc, "Migration & deploy": 0002 drops the account tables.)
EXPECTED_CONSTRAINTS = {
    "pk_receipts": "p",
    "pk_parse_attempts": "p",
    "pk_corrections": "p",
    "uq_parse_attempts_receipt_id_attempt_number": "u",
    "uq_parse_attempts_id_receipt_id": "u",
    "uq_corrections_parse_attempt_id_sequence": "u",
    "ck_receipts_status_valid": "c",
    "ck_receipts_manual_retry_count_range": "c",
    "ck_parse_attempts_attempt_number_positive": "c",
    "ck_parse_attempts_trigger_valid": "c",
    "ck_parse_attempts_outcome_valid": "c",
    "ck_corrections_sequence_positive": "c",
    "ck_corrections_kind_valid": "c",
    "fk_receipts_active_parse_attempt_id_parse_attempts": "f",
    "fk_parse_attempts_receipt_id_receipts": "f",
    "fk_corrections_receipt_id_receipts": "f",
    "fk_corrections_attempt_receipt": "f",
}

DROPPED_TABLES = ("users", "households", "participants", "assignments", "allocation_snapshots")


def test_round_trip(alembic_config: Config, migrated_engine: Engine) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


def test_orm_matches_migration(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []


def test_catalog_names_and_predicates(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT c.conname, c.contype, c.condeferrable, c.condeferred
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname <> 'alembic_version'
                  -- Postgres 18+ also records NOT NULL as auto-named constraints (contype 'n');
                  -- nullability is already verified by test_orm_matches_migration.
                  AND c.contype <> 'n'
                """
            )
        ).all()
        indexes = dict(
            connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
            ).all()
        )

    assert {row.conname: row.contype for row in rows} == EXPECTED_CONSTRAINTS
    for row in rows:
        assert len(row.conname) <= 63
        if row.contype == "f":
            expected_deferred = row.conname in DEFERRED_FKS
            assert row.condeferrable is expected_deferred, row.conname
            assert row.condeferred is expected_deferred, row.conname

    assert "ix_receipts_expires_at" in indexes
    assert "uq_participants_active_display_name" not in indexes


def _public_tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )


def test_upgrade_from_0001_with_data(alembic_config: Config, migrated_engine: Engine) -> None:
    """0002 must upgrade a 0001 database that has rows, and downgrade back cleanly."""
    try:
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, "0001")
        with migrated_engine.begin() as connection:
            user_id = connection.execute(
                text("INSERT INTO users (email) VALUES ('a@test.local') RETURNING id")
            ).scalar_one()
            household_id = connection.execute(
                text("INSERT INTO households (owner_user_id, name) VALUES (:u, 'H') RETURNING id"),
                {"u": user_id},
            ).scalar_one()
            participant_id = connection.execute(
                text(
                    "INSERT INTO participants (household_id, display_name, sort_order) "
                    "VALUES (:h, 'P', 0) RETURNING id"
                ),
                {"h": household_id},
            ).scalar_one()
            receipt_id = connection.execute(
                text(
                    "INSERT INTO receipts (household_id, payer_participant_id, status) "
                    "VALUES (:h, :p, 'needs_review') RETURNING id"
                ),
                {"h": household_id, "p": participant_id},
            ).scalar_one()
            attempt_id = connection.execute(
                text(
                    "INSERT INTO parse_attempts (receipt_id, attempt_number, trigger, provider, "
                    "model, prompt_version, outcome) "
                    "VALUES (:r, 1, 'initial', 't', 't', 'v0', 'ok') RETURNING id"
                ),
                {"r": receipt_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO assignments (parse_attempt_id, line_id, participant_id) "
                    "VALUES (:a, 'L1', :p)"
                ),
                {"a": attempt_id, "p": participant_id},
            )

        command.upgrade(alembic_config, "head")
        tables = _public_tables(migrated_engine)
        assert not (set(DROPPED_TABLES) & tables)
        with migrated_engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM receipts")).scalar_one() == 0

        command.downgrade(alembic_config, "0001")
        tables = _public_tables(migrated_engine)
        assert set(DROPPED_TABLES) <= tables
        with migrated_engine.connect() as connection:
            for table in (*DROPPED_TABLES, "receipts"):
                count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                assert count == 0, table
    finally:
        # Later tests expect head.
        command.upgrade(alembic_config, "head")
