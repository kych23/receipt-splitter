import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from strategies import allocation_inputs

from app.db.models import Receipt
from app.domain.allocation import AllocationInput
from app.domain.receipt import ParsedReceipt
from app.receipts import service
from app.receipts.example import EXAMPLE_STATE
from app.receipts.purge import purge_expired
from app.receipts.schemas import Participant, ReceiptState
from app.receipts.service import (
    ReceiptNotFound,
    ReceiptValidationError,
    ServiceBusy,
    compute_allocation,
    create_receipt,
    delete_receipt,
    get_receipt,
    save_receipt,
    to_response,
    validate_state,
)

A = UUID("00000000-0000-4000-8000-00000000000a")
B = UUID("00000000-0000-4000-8000-00000000000b")


def _line(line_id: str, kind: str = "item", total_cents: int = 100, **extra: Any) -> dict[str, Any]:
    return {"line_id": line_id, "kind": kind, "name": "x", "total_cents": total_cents, **extra}


def _state(
    lines: list[dict[str, Any]],
    people: list[tuple[UUID, str]],
    tags: dict[str, list[UUID]],
    tax: int | None = None,
) -> ReceiptState:
    return ReceiptState(
        content=ParsedReceipt.model_validate(
            {
                "lines": lines,
                "tax_lines": [] if tax is None else [{"label": "Tax", "amount_cents": tax}],
            }
        ),
        participants=[Participant(key=key, display_name=name) for key, name in people],
        assignments=tags,
    )


# ---------------------------------------------------------------------------------------------
# validate_state
# ---------------------------------------------------------------------------------------------


def test_valid_state_passes() -> None:
    validate_state(_state([_line("L1")], [(A, "Alex"), (B, "Sam")], {"L1": [A, B]}))


INVALID_STATES = {
    "duplicate-key": (
        _state([_line("L1")], [(A, "Alex"), (A, "Sam")], {"L1": [A]}),
        "duplicate participant key",
    ),
    "duplicate-name-case": (
        _state([_line("L1")], [(A, "Alex"), (B, " alex ")], {"L1": [A]}),
        "duplicate person name",
    ),
    "tag-unknown-line": (
        _state([_line("L1")], [(A, "Alex")], {"L1": [A], "ZZ": [A]}),
        "tag on unknown or non-item line: ZZ",
    ),
    "tag-non-item-line": (
        _state([_line("L1"), _line("F1", "fee", 10)], [(A, "Alex")], {"L1": [A], "F1": [A]}),
        "tag on unknown or non-item line: F1",
    ),
    "tag-unknown-person": (
        _state([_line("L1")], [(A, "Alex")], {"L1": [B]}),
        "tag references unknown person",
    ),
    "empty-tag-list": (
        _state([_line("L1")], [(A, "Alex")], {"L1": []}),
        "empty or duplicate tag list: L1",
    ),
    "duplicate-tag-list": (
        _state([_line("L1")], [(A, "Alex")], {"L1": [A, A]}),
        "empty or duplicate tag list: L1",
    ),
}


@pytest.mark.parametrize(
    ("state", "message"),
    [pytest.param(state, message, id=case) for case, (state, message) in INVALID_STATES.items()],
)
def test_invalid_states_rejected(state: ReceiptState, message: str) -> None:
    with pytest.raises(ReceiptValidationError) as exc_info:
        validate_state(state)
    assert any(message in problem for problem in exc_info.value.problems)


def test_deposit_lines_are_taggable() -> None:
    validate_state(_state([_line("D1", "deposit", 5)], [(A, "Alex")], {"D1": [A]}))


def test_state_over_size_cap_rejected() -> None:
    lines = [_line(f"L{i:03d}" + "x" * 30, name="n" * 120) for i in range(300)]
    people = [(UUID(int=i + 1), f"Person {i:02d}") for i in range(20)]
    tags = {line["line_id"]: [key for key, _ in people] for line in lines}
    state = _state(lines, people, tags)
    with pytest.raises(ReceiptValidationError) as exc_info:
        validate_state(state)
    assert "receipt too large" in exc_info.value.problems


# ---------------------------------------------------------------------------------------------
# compute_allocation and the example receipt
# ---------------------------------------------------------------------------------------------


def test_example_allocates_to_pinned_table() -> None:
    allocation, problem = compute_allocation(EXAMPLE_STATE)
    assert problem is None
    assert allocation is not None
    rows = {str(p.participant_id): p for p in allocation.participants}
    alex, sam, jordan = (
        rows["00000000-0000-4000-8000-000000000001"],
        rows["00000000-0000-4000-8000-000000000002"],
        rows["00000000-0000-4000-8000-000000000003"],
    )
    assert (alex.items_cents, alex.tax_cents, alex.total_cents) == (412, 14, 426)
    assert (sam.items_cents, sam.tax_cents, sam.total_cents) == (1410, 93, 1503)
    assert (jordan.items_cents, jordan.tax_cents, jordan.total_cents) == (1741, 139, 1880)
    assert [(s.line_id, s.share_cents) for s in alex.line_shares] == [("ex-1", 245), ("ex-5", 167)]
    assert [(s.line_id, s.share_cents) for s in sam.line_shares] == [
        ("ex-1", 244),
        ("ex-3", 999),
        ("ex-5", 167),
    ]
    assert allocation.computed_total_cents == 3809
    assert allocation.printed_total_cents == 3809
    assert allocation.warnings == []


def test_mid_edit_states_return_a_problem_not_an_error() -> None:
    no_people = _state([_line("L1")], [], {})
    untagged = _state([_line("L1"), _line("L2")], [(A, "Alex")], {"L1": [A]})
    assert compute_allocation(no_people)[1].code == "no_participants"  # type: ignore[union-attr]
    assert compute_allocation(untagged)[1].code == "unassigned_line"  # type: ignore[union-attr]


@st.composite
def service_states(draw: st.DrawFn) -> ReceiptState:
    """Service-valid states that may be incomplete for allocation (people/tags dropped)."""
    inp: AllocationInput = draw(allocation_inputs())
    keep_people = [pid for pid in inp.participant_ids if draw(st.booleans())]
    assignments: dict[str, list[UUID]] = {}
    for line_id, keys in inp.assignments.items():
        if draw(st.booleans()):
            continue  # drop this tag entirely -> untagged line
        deduped = list(dict.fromkeys(k for k in keys if k in keep_people))
        if deduped:
            assignments[line_id] = deduped
    participants = [Participant(key=pid, display_name=f"P{i}") for i, pid in enumerate(keep_people)]
    return ReceiptState(content=inp.receipt, participants=participants, assignments=assignments)


@given(state=service_states())
def test_compute_allocation_returns_exactly_one_and_sums(state: ReceiptState) -> None:
    validate_state(state)
    allocation, problem = compute_allocation(state)
    assert (allocation is None) != (problem is None)
    if allocation is not None:
        total = sum(p.total_cents for p in allocation.participants)
        assert total == allocation.computed_total_cents


@given(state=service_states())
def test_json_round_trip_gives_the_same_allocation(state: ReceiptState) -> None:
    reloaded = ReceiptState.model_validate(json.loads(json.dumps(state.model_dump(mode="json"))))
    assert compute_allocation(reloaded) == compute_allocation(state)


# ---------------------------------------------------------------------------------------------
# DB-backed operations
# ---------------------------------------------------------------------------------------------


def _backdate(session: Session, receipt_id: UUID) -> None:
    session.execute(
        text("UPDATE receipts SET expires_at = now() - interval '1 minute' WHERE id = :id"),
        {"id": receipt_id},
    )
    session.expire_all()


@pytest.mark.db
def test_create_empty_and_example(db_session: Session) -> None:
    empty = create_receipt(db_session, example=False)
    example = create_receipt(db_session, example=True)
    assert empty.is_example is False
    assert ParsedReceipt.model_validate(empty.content).lines == []
    assert example.is_example is True
    assert to_response(example).allocation is not None
    assert to_response(example).allocation.computed_total_cents == 3809  # type: ignore[union-attr]


@pytest.mark.db
def test_get_save_delete_and_expiry(db_session: Session) -> None:
    receipt = create_receipt(db_session, example=False)
    before_expires, before_updated = receipt.expires_at, receipt.updated_at

    saved = save_receipt(
        db_session, receipt.id, _state([_line("L1", total_cents=1000)], [(A, "A")], {"L1": [A]})
    )
    assert saved.expires_at > before_expires
    assert saved.updated_at > before_updated
    assert get_receipt(db_session, receipt.id).participants == [
        {"key": str(A), "display_name": "A"}
    ]

    _backdate(db_session, receipt.id)
    with pytest.raises(ReceiptNotFound):
        get_receipt(db_session, receipt.id)
    with pytest.raises(ReceiptNotFound):
        save_receipt(db_session, receipt.id, _state([], [], {}))
    with pytest.raises(ReceiptNotFound):
        delete_receipt(db_session, receipt.id)


@pytest.mark.db
def test_delete_then_not_found(db_session: Session) -> None:
    receipt = create_receipt(db_session, example=False)
    delete_receipt(db_session, receipt.id)
    with pytest.raises(ReceiptNotFound):
        get_receipt(db_session, receipt.id)


@pytest.mark.db
def test_purge_deletes_only_expired(db_session: Session) -> None:
    live_id = create_receipt(db_session, example=False).id
    stale_id = create_receipt(db_session, example=False).id
    _backdate(db_session, stale_id)

    assert purge_expired(db_session) == 1
    remaining = set(db_session.scalars(select(Receipt.id)))
    assert live_id in remaining
    assert stale_id not in remaining


@pytest.mark.db
def test_create_refuses_at_live_cap(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "MAX_LIVE_RECEIPTS", 2)
    create_receipt(db_session, example=False)
    stale = create_receipt(db_session, example=False)
    _backdate(db_session, stale.id)
    create_receipt(db_session, example=False)  # the expired one is purged first, so this fits

    with pytest.raises(ServiceBusy):
        create_receipt(db_session, example=False)
    live = db_session.scalar(
        select(func.count()).select_from(Receipt).where(Receipt.expires_at > func.now())
    )
    assert live == 2


def test_web_example_fixture_matches_the_server_example() -> None:
    """The web tests' copy of the example (web/src/test/example-receipt.json) must not drift."""
    fixture_path = Path(__file__).resolve().parents[3] / "web/src/test/example-receipt.json"
    fixture = json.loads(fixture_path.read_text())
    allocation, problem = compute_allocation(EXAMPLE_STATE)
    assert problem is None and allocation is not None
    assert {k: fixture[k] for k in ("content", "participants", "assignments")} == (
        EXAMPLE_STATE.model_dump(mode="json")
    )
    assert fixture["allocation"] == allocation.model_dump(mode="json")


@pytest.mark.db
def test_unsaved_receipt_expires_in_an_hour_and_first_save_extends_to_a_day(
    db_session: Session,
) -> None:
    receipt = create_receipt(db_session, example=False)
    lifetime = db_session.scalar(
        select(Receipt.expires_at - func.clock_timestamp()).where(Receipt.id == receipt.id)
    )
    assert timedelta(minutes=59) < lifetime <= service.UNSAVED_RECEIPT_TTL
    saved = save_receipt(db_session, receipt.id, _state([], [], {}))
    lifetime = db_session.scalar(
        select(Receipt.expires_at - func.clock_timestamp()).where(Receipt.id == saved.id)
    )
    assert timedelta(hours=23, minutes=59) < lifetime <= service.RECEIPT_TTL


@pytest.mark.db
def test_save_after_concurrent_delete_is_not_found(db_session: Session) -> None:
    """Regression: a DELETE landing between load and write must be a 404, not a StaleDataError."""
    receipt = create_receipt(db_session, example=False)
    get_receipt(db_session, receipt.id)  # row now in the identity map, as in a real request
    db_session.execute(text("DELETE FROM receipts WHERE id = :id"), {"id": receipt.id})
    with pytest.raises(ReceiptNotFound):
        save_receipt(db_session, receipt.id, _state([], [], {}))
