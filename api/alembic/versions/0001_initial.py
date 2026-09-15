"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-15

Hand-written to mirror app/db/models.py exactly. Every constraint/index name is wrapped in
``op.f()`` because env.py's target metadata carries a naming convention that would otherwise be
applied a second time (e.g. ``ck_receipts_ck_receipts_status_valid``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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

    op.create_table(
        "receipts",
        _id(),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payer_participant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("image_object_key", sa.Text(), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("active_parse_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("manual_retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipts")),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
            name=op.f("fk_receipts_household_id_households"),
        ),
        sa.ForeignKeyConstraint(
            ["payer_participant_id"],
            ["participants.id"],
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
            name=op.f("fk_receipts_payer_participant_id_participants"),
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'parsing', 'needs_review', 'finalized', 'parse_failed')",
            name=op.f("ck_receipts_status_valid"),
        ),
        sa.CheckConstraint(
            "manual_retry_count BETWEEN 0 AND 5",
            name=op.f("ck_receipts_manual_retry_count_range"),
        ),
    )

    op.create_table(
        "parse_attempts",
        _id(),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("parsed", postgresql.JSONB(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("check_results", postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parse_attempts")),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["receipts.id"],
            ondelete="CASCADE",
            name=op.f("fk_parse_attempts_receipt_id_receipts"),
        ),
        sa.UniqueConstraint(
            "receipt_id",
            "attempt_number",
            name=op.f("uq_parse_attempts_receipt_id_attempt_number"),
        ),
        sa.UniqueConstraint("id", "receipt_id", name=op.f("uq_parse_attempts_id_receipt_id")),
        sa.CheckConstraint(
            "attempt_number >= 1", name=op.f("ck_parse_attempts_attempt_number_positive")
        ),
        sa.CheckConstraint(
            "trigger IN ('initial', 'auto_retry', 'manual_retry')",
            name=op.f("ck_parse_attempts_trigger_valid"),
        ),
        sa.CheckConstraint(
            "outcome IN ('ok', 'invalid_output', 'provider_error')",
            name=op.f("ck_parse_attempts_outcome_valid"),
        ),
    )

    # Circular reference: receipts.active_parse_attempt_id → parse_attempts, added after both exist.
    op.create_foreign_key(
        op.f("fk_receipts_active_parse_attempt_id_parse_attempts"),
        "receipts",
        "parse_attempts",
        ["active_parse_attempt_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "corrections",
        _id(),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parse_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("line_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corrections")),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["receipts.id"],
            ondelete="CASCADE",
            name=op.f("fk_corrections_receipt_id_receipts"),
        ),
        sa.ForeignKeyConstraint(
            ["parse_attempt_id", "receipt_id"],
            ["parse_attempts.id", "parse_attempts.receipt_id"],
            ondelete="CASCADE",
            name=op.f("fk_corrections_attempt_receipt"),
        ),
        sa.UniqueConstraint(
            "parse_attempt_id", "sequence", name=op.f("uq_corrections_parse_attempt_id_sequence")
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_corrections_sequence_positive")),
        sa.CheckConstraint(
            "kind IN ('add_line', 'update_line', 'delete_line', 'update_totals')",
            name=op.f("ck_corrections_kind_valid"),
        ),
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


def downgrade() -> None:
    # Drop the circular FK first so the tables can be dropped in reverse creation order.
    op.drop_constraint(
        op.f("fk_receipts_active_parse_attempt_id_parse_attempts"), "receipts", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_allocation_snapshots_receipt_id_created_at"), table_name="allocation_snapshots"
    )
    op.drop_table("allocation_snapshots")
    op.drop_table("assignments")
    op.drop_table("corrections")
    op.drop_table("parse_attempts")
    op.drop_table("receipts")
    op.drop_index(op.f("uq_participants_active_display_name"), table_name="participants")
    op.drop_table("participants")
    op.drop_table("households")
    op.drop_table("users")
