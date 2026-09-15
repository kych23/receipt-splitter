import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text

import app.db.models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base

pytestmark = pytest.mark.db

DEFERRED_FKS = {
    "fk_receipts_payer_participant_id_participants",
    "fk_assignments_participant_id_participants",
}

# Every constraint in the public schema, by name → pg_constraint.contype (design doc A4.1).
EXPECTED_CONSTRAINTS = {
    **{
        f"pk_{table}": "p"
        for table in (
            "users",
            "households",
            "participants",
            "receipts",
            "parse_attempts",
            "corrections",
            "assignments",
            "allocation_snapshots",
        )
    },
    "uq_users_email": "u",
    "uq_parse_attempts_receipt_id_attempt_number": "u",
    "uq_parse_attempts_id_receipt_id": "u",
    "uq_corrections_parse_attempt_id_sequence": "u",
    "ck_households_name_length": "c",
    "ck_participants_display_name_length": "c",
    "ck_receipts_status_valid": "c",
    "ck_receipts_manual_retry_count_range": "c",
    "ck_parse_attempts_attempt_number_positive": "c",
    "ck_parse_attempts_trigger_valid": "c",
    "ck_parse_attempts_outcome_valid": "c",
    "ck_corrections_sequence_positive": "c",
    "ck_corrections_kind_valid": "c",
    "fk_households_owner_user_id_users": "f",
    "fk_participants_household_id_households": "f",
    "fk_receipts_household_id_households": "f",
    "fk_receipts_payer_participant_id_participants": "f",
    "fk_receipts_active_parse_attempt_id_parse_attempts": "f",
    "fk_parse_attempts_receipt_id_receipts": "f",
    "fk_corrections_receipt_id_receipts": "f",
    "fk_corrections_attempt_receipt": "f",
    "fk_assignments_parse_attempt_id_parse_attempts": "f",
    "fk_assignments_participant_id_participants": "f",
    "fk_allocation_snapshots_receipt_id_receipts": "f",
    "fk_allocation_snapshots_attempt_receipt": "f",
}


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

    partial = indexes["uq_participants_active_display_name"]
    assert "UNIQUE" in partial
    assert partial.endswith("WHERE (archived_at IS NULL)")
    assert "ix_allocation_snapshots_receipt_id_created_at" in indexes
