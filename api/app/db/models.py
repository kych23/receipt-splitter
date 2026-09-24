"""ORM models. Must stay in exact parity with the Alembic migrations (tests/db/test_migrations.py).

Revision 6/7 scope: no accounts, no saved people, no receipt history. A receipt is an ephemeral row
holding the receipt being split (``content``), the people splitting it and the item tags, and it
expires 24 hours after its last save (see docs/design/slice-3-manual-split.md).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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

RECEIPT_STATUSES = ("draft", "uploaded", "parsing", "needs_review", "finalized", "parse_failed")
EMPTY_CONTENT_SQL = """'{"lines": [], "tax_lines": []}'::jsonb"""
EXPIRES_AT_DEFAULT_SQL = "(now() + interval '24 hours')"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in RECEIPT_STATUSES) + ")",
            name="status_valid",
        ),
        CheckConstraint("manual_retry_count BETWEEN 0 AND 5", name="manual_retry_count_range"),
        Index("ix_receipts_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
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
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text(EMPTY_CONTENT_SQL)
    )
    participants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    assignments: Mapped[dict[str, list[str]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_example: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created_at()
    # clock_timestamp() (not now()) so updates advance even inside one transaction.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.clock_timestamp(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text(EXPIRES_AT_DEFAULT_SQL)
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
