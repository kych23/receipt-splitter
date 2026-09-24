from datetime import datetime, timedelta
from typing import Any

import pytest
from conftest import make_graph
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Correction, ParseAttempt, Receipt
from app.domain.receipt import ParsedReceipt

pytestmark = pytest.mark.db


def _count(session: Session, model: Any, *criteria: Any) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*criteria)) or 0


def _expect_integrity_error(session: Session, action: Any) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        action()
        session.flush()


def test_graph_inserts(db_session: Session) -> None:
    make_graph(db_session)


def test_receipt_defaults(db_session: Session) -> None:
    receipt = Receipt()
    db_session.add(receipt)
    db_session.flush()
    db_session.refresh(receipt)
    db_now: datetime = db_session.scalar(select(func.clock_timestamp()))

    assert receipt.status == "draft"
    assert receipt.is_example is False
    assert receipt.participants == []
    assert receipt.assignments == {}
    assert ParsedReceipt.model_validate(receipt.content).lines == []
    assert db_now + timedelta(hours=23, minutes=59) < receipt.expires_at
    assert receipt.expires_at <= db_now + timedelta(hours=24)


def test_draft_status_accepted_and_unknown_rejected(db_session: Session) -> None:
    db_session.add(Receipt(status="draft"))
    db_session.flush()

    def action() -> None:
        db_session.add(Receipt(status="bogus"))

    _expect_integrity_error(db_session, action)


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


def test_correction_receipt_must_match_attempt_receipt(db_session: Session) -> None:
    g = make_graph(db_session)
    other_receipt = Receipt()
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


def test_delete_parse_attempt_nulls_active_pointer(db_session: Session) -> None:
    g = make_graph(db_session)
    assert db_session.get_one(Receipt, g.receipt_id).active_parse_attempt_id == g.attempt_id
    assert _count(db_session, Correction, Correction.parse_attempt_id == g.attempt_id) == 1

    db_session.execute(delete(ParseAttempt).where(ParseAttempt.id == g.attempt_id))
    db_session.expire_all()

    assert db_session.get_one(Receipt, g.receipt_id).active_parse_attempt_id is None
    assert _count(db_session, Correction, Correction.parse_attempt_id == g.attempt_id) == 0


def test_delete_receipt_cascades(db_session: Session) -> None:
    g = make_graph(db_session)
    assert _count(db_session, ParseAttempt, ParseAttempt.receipt_id == g.receipt_id) == 1
    assert _count(db_session, Correction, Correction.receipt_id == g.receipt_id) == 1

    db_session.execute(delete(Receipt).where(Receipt.id == g.receipt_id))

    assert _count(db_session, ParseAttempt, ParseAttempt.receipt_id == g.receipt_id) == 0
    assert _count(db_session, Correction, Correction.receipt_id == g.receipt_id) == 0


def test_expires_at_can_be_backdated(db_session: Session) -> None:
    receipt = Receipt()
    db_session.add(receipt)
    db_session.flush()
    db_session.execute(
        text("UPDATE receipts SET expires_at = now() - interval '1 minute' WHERE id = :id"),
        {"id": receipt.id},
    )
    db_session.refresh(receipt)
    assert receipt.expires_at < db_session.scalar(select(func.clock_timestamp()))
