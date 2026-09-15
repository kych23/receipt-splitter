"""ORM models. Must stay in exact parity with alembic/versions/0001_initial.py.

Participants are never hard-deleted by the app (archive via ``archived_at``). The two FKs that
reference participants are DEFERRABLE INITIALLY DEFERRED so deleting a household/user can cascade
through receipts → parse_attempts → assignments before the participant reference is checked.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = _created_at()


class Household(Base):
    __tablename__ = "households"
    __table_args__ = (CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (
        CheckConstraint("char_length(display_name) BETWEEN 1 AND 40", name="display_name_length"),
        Index(
            "uq_participants_active_display_name",
            "household_id",
            "display_name",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'parsing', 'needs_review', 'finalized', 'parse_failed')",
            name="status_valid",
        ),
        CheckConstraint("manual_retry_count BETWEEN 0 AND 5", name="manual_retry_count_range"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    payer_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="NO ACTION", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    image_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_parse_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parse_attempts.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    manual_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ParseAttempt(Base):
    __tablename__ = "parse_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
        CheckConstraint(
            "trigger IN ('initial', 'auto_retry', 'manual_retry')", name="trigger_valid"
        ),
        CheckConstraint(
            "outcome IN ('ok', 'invalid_output', 'provider_error')", name="outcome_valid"
        ),
        UniqueConstraint("receipt_id", "attempt_number"),
        UniqueConstraint("id", "receipt_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_microusd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = _created_at()


class Correction(Base):
    __tablename__ = "corrections"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(
            "kind IN ('add_line', 'update_line', 'delete_line', 'update_totals')",
            name="kind_valid",
        ),
        UniqueConstraint("parse_attempt_id", "sequence"),
        ForeignKeyConstraint(
            ["parse_attempt_id", "receipt_id"],
            ["parse_attempts.id", "parse_attempts.receipt_id"],
            ondelete="CASCADE",
            name="fk_corrections_attempt_receipt",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    parse_attempt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    line_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Assignment(Base):
    __tablename__ = "assignments"

    parse_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parse_attempts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    line_id: Mapped[str] = mapped_column(Text, primary_key=True)
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="NO ACTION", deferrable=True, initially="DEFERRED"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = _created_at()


class AllocationSnapshot(Base):
    __tablename__ = "allocation_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["parse_attempt_id", "receipt_id"],
            ["parse_attempts.id", "parse_attempts.receipt_id"],
            ondelete="CASCADE",
            name="fk_allocation_snapshots_attempt_receipt",
        ),
        Index("ix_allocation_snapshots_receipt_id_created_at", "receipt_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    parse_attempt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    allocator_version: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at()
