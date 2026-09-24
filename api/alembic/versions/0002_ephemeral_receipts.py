"""ephemeral receipts: drop account tables, reshape receipts

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24

Implements docs/design/slice-3-manual-split.md ("Migration & deploy"). There are no accounts, saved
people or receipt history, so the account tables go and a receipt becomes an ephemeral row that
holds the receipt being split, the people and the tags, and expires 24 hours after its last save.

Deliberate one-step contract (recorded in the v0 design doc, revision 7): safe because the deployed
Slice 1 app never queries any of these tables; its only statement is ``SELECT 1`` in ``/readyz``.

All constraint/index names are wrapped in ``op.f()`` so env.py's naming convention is not applied a
second time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = "status IN ('uploaded', 'parsing', 'needs_review', 'finalized', 'parse_failed')"
NEW_STATUSES = (
    "status IN ('draft', 'uploaded', 'parsing', 'needs_review', 'finalized', 'parse_failed')"
)
EMPTY_CONTENT_SQL = """'{"lines": [], "tax_lines": []}'::jsonb"""
EXPIRES_AT_DEFAULT_SQL = "(now() + interval '24 hours')"


def _id() -> sa.Column[object]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    # Receipts are ephemeral by design; any existing rows are disposable. Cascades to
    # parse_attempts, corrections, assignments and allocation_snapshots.
    op.execute("DELETE FROM receipts")

    op.drop_index(
        op.f("ix_allocation_snapshots_receipt_id_created_at"), table_name="allocation_snapshots"
    )
    op.drop_table("allocation_snapshots")
    op.drop_table("assignments")

    op.drop_constraint(
        op.f("fk_receipts_payer_participant_id_participants"), "receipts", type_="foreignkey"
    )
    op.drop_column("receipts", "payer_participant_id")
    op.drop_constraint(op.f("fk_receipts_household_id_households"), "receipts", type_="foreignkey")
    op.drop_column("receipts", "household_id")

    op.drop_index(op.f("uq_participants_active_display_name"), table_name="participants")
    op.drop_table("participants")
    op.drop_table("households")
    op.drop_table("users")

    op.add_column(
        "receipts",
        sa.Column(
            "content", postgresql.JSONB(), server_default=sa.text(EMPTY_CONTENT_SQL), nullable=False
        ),
    )
    op.add_column(
        "receipts",
        sa.Column(
            "participants",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "receipts",
        sa.Column(
            "assignments",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "receipts",
        sa.Column("is_example", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "receipts",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.text(EXPIRES_AT_DEFAULT_SQL),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_receipts_expires_at"), "receipts", ["expires_at"])

    op.drop_constraint(op.f("ck_receipts_status_valid"), "receipts", type_="check")
    op.create_check_constraint(op.f("ck_receipts_status_valid"), "receipts", NEW_STATUSES)
    op.alter_column("receipts", "status", server_default=sa.text("'draft'"))


def downgrade() -> None:
    # Receipts are ephemeral; 0001 requires household_id NOT NULL, so rows cannot survive.
    op.execute("DELETE FROM receipts")

    op.alter_column("receipts", "status", server_default=None)
    op.drop_constraint(op.f("ck_receipts_status_valid"), "receipts", type_="check")
    op.create_check_constraint(op.f("ck_receipts_status_valid"), "receipts", OLD_STATUSES)

    op.drop_index(op.f("ix_receipts_expires_at"), table_name="receipts")
    for column in ("expires_at", "is_example", "assignments", "participants", "content"):
        op.drop_column("receipts", column)

    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.Text(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "households",
        _id(),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_households")),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name=op.f("fk_households_owner_user_id_users"),
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80", name=op.f("ck_households_name_length")
        ),
    )
    op.create_table(
        "participants",
        _id(),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participants")),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
            name=op.f("fk_participants_household_id_households"),
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 40",
            name=op.f("ck_participants_display_name_length"),
        ),
    )
    op.create_index(
        op.f("uq_participants_active_display_name"),
        "participants",
        ["household_id", "display_name"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.add_column(
        "receipts",
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_receipts_household_id_households"),
        "receipts",
        "households",
        ["household_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "receipts",
        sa.Column("payer_participant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_receipts_payer_participant_id_participants"),
        "receipts",
        "participants",
        ["payer_participant_id"],
        ["id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "assignments",
        sa.Column("parse_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_id", sa.Text(), nullable=False),
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint(
            "parse_attempt_id", "line_id", "participant_id", name=op.f("pk_assignments")
        ),
        sa.ForeignKeyConstraint(
            ["parse_attempt_id"],
            ["parse_attempts.id"],
            ondelete="CASCADE",
            name=op.f("fk_assignments_parse_attempt_id_parse_attempts"),
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
            name=op.f("fk_assignments_participant_id_participants"),
        ),
    )
    op.create_table(
        "allocation_snapshots",
        _id(),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parse_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocator_version", sa.Text(), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_allocation_snapshots")),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["receipts.id"],
            ondelete="CASCADE",
            name=op.f("fk_allocation_snapshots_receipt_id_receipts"),
        ),
        sa.ForeignKeyConstraint(
            ["parse_attempt_id", "receipt_id"],
            ["parse_attempts.id", "parse_attempts.receipt_id"],
            ondelete="CASCADE",
            name=op.f("fk_allocation_snapshots_attempt_receipt"),
        ),
    )
    op.create_index(
        op.f("ix_allocation_snapshots_receipt_id_created_at"),
        "allocation_snapshots",
        ["receipt_id", "created_at"],
    )
