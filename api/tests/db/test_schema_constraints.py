from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import Graph, make_graph
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    AllocationSnapshot,
    Assignment,
    Correction,
    Household,
    ParseAttempt,
    Participant,
    Receipt,
)

pytestmark = pytest.mark.db


def _immediate(session: Session) -> None:
    """Force deferred constraint checks now instead of at (never-reached) commit."""
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def _count(session: Session, model: Any, *criteria: Any) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*criteria)) or 0


def _expect_integrity_error(session: Session, action: Any) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        action()
        session.flush()
        _immediate(session)


def test_graph_inserts(db_session: Session) -> None:
    make_graph(db_session)
    _immediate(db_session)


def test_manual_retry_count_capped_at_five(db_session: Session) -> None:
    g = make_graph(db_session)
    receipt = db_session.get_one(Receipt, g.receipt_id)

    def action() -> None:
        receipt.manual_retry_count = 6

    _expect_integrity_error(db_session, action)


def test_duplicate_attempt_number_rejected(db_session: Session) -> None:
    g = make_graph(db_session)

    def action() -> None:
        db_session.add(
            ParseAttempt(
                receipt_id=g.receipt_id,
                attempt_number=1,
                trigger="manual_retry",
                provider="test",
                model="test",
                prompt_version="v0",
                outcome="ok",
            )
        )

    _expect_integrity_error(db_session, action)


def test_duplicate_active_participant_name_rejected(db_session: Session) -> None:
    g = make_graph(db_session)

    def action() -> None:
        db_session.add(Participant(household_id=g.household_id, display_name="P1", sort_order=5))

    _expect_integrity_error(db_session, action)


def test_correction_receipt_must_match_attempt_receipt(db_session: Session) -> None:
    g = make_graph(db_session)
    other_receipt = Receipt(household_id=g.household_id, status="uploaded")
    db_session.add(other_receipt)
    db_session.flush()

    def action() -> None:
        db_session.add(
            Correction(
                receipt_id=other_receipt.id,
                parse_attempt_id=g.attempt_id,
                sequence=2,
                kind="update_line",
                payload={},
            )
        )

    _expect_integrity_error(db_session, action)


def test_archived_name_can_be_reused(db_session: Session) -> None:
    g = make_graph(db_session)
    db_session.get_one(Participant, g.payer_id).archived_at = datetime.now(UTC)
    db_session.flush()
    db_session.add(Participant(household_id=g.household_id, display_name="P1", sort_order=2))
    db_session.flush()


def test_delete_parse_attempt_nulls_active_pointer(db_session: Session) -> None:
    g: Graph = make_graph(db_session)
    assert db_session.get_one(Receipt, g.receipt_id).active_parse_attempt_id == g.attempt_id
    for model in (Correction, Assignment, AllocationSnapshot):
        assert _count(db_session, model, model.parse_attempt_id == g.attempt_id) == 1

    db_session.execute(delete(ParseAttempt).where(ParseAttempt.id == g.attempt_id))
    _immediate(db_session)
    db_session.expire_all()

    assert db_session.get_one(Receipt, g.receipt_id).active_parse_attempt_id is None
    for model in (Correction, Assignment, AllocationSnapshot):
        assert _count(db_session, model, model.parse_attempt_id == g.attempt_id) == 0


def _household_counts(session: Session, g: Graph) -> tuple[int, ...]:
    return (
        _count(session, Receipt, Receipt.household_id == g.household_id),
        _count(session, ParseAttempt, ParseAttempt.id == g.attempt_id),
        _count(session, Correction, Correction.receipt_id == g.receipt_id),
        _count(session, Assignment, Assignment.parse_attempt_id == g.attempt_id),
        _count(session, AllocationSnapshot, AllocationSnapshot.receipt_id == g.receipt_id),
        _count(session, Participant, Participant.household_id == g.household_id),
    )


def test_delete_household_cascades(db_session: Session) -> None:
    g = make_graph(db_session)
    assert _household_counts(db_session, g) == (1, 1, 1, 1, 1, 2)

    db_session.execute(delete(Household).where(Household.id == g.household_id))
    _immediate(db_session)

    assert _household_counts(db_session, g) == (0, 0, 0, 0, 0, 0)


def test_delete_referenced_participant_fails(db_session: Session) -> None:
    g = make_graph(db_session)

    def action() -> None:
        db_session.execute(delete(Participant).where(Participant.id == g.member_id))

    _expect_integrity_error(db_session, action)
