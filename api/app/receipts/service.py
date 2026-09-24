"""Receipt operations: validation, allocation, and the ephemeral-row lifecycle.

See docs/design/slice-3-manual-split.md ("Service"). The service owns ``commit()``; routes only map
exceptions to HTTP responses.
"""

import json
from datetime import timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, func, select, update
from sqlalchemy.orm import Session

from app.db.models import Receipt
from app.domain.allocation import AllocationError, AllocationInput, AllocationResult, allocate
from app.domain.receipt import ASSIGNABLE_KINDS
from app.receipts.example import EXAMPLE_STATE
from app.receipts.purge import purge_expired
from app.receipts.schemas import AllocationProblem, ReceiptResponse, ReceiptState

MAX_LIVE_RECEIPTS = 10_000
MAX_STATE_BYTES = 262_144
RECEIPT_TTL = timedelta(hours=24)
# A receipt nobody has saved yet is cheap to recreate; expiring it quickly stops a burst of
# creates from holding live-receipt slots (and blocking everyone with 503s) for a whole day.
UNSAVED_RECEIPT_TTL = timedelta(hours=1)


class ReceiptNotFound(Exception):
    """The receipt does not exist or has expired."""


class ServiceBusy(Exception):
    """The live-receipt cap is reached; creating another would exceed the storage budget."""


class ReceiptValidationError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _state_json(state: ReceiptState) -> dict[str, object]:
    dumped: dict[str, object] = state.model_dump(mode="json")
    return dumped


def validate_state(state: ReceiptState) -> None:
    """Cross-field rules the pydantic models can't express. Raises ``ReceiptValidationError``."""
    problems: list[str] = []

    keys = [p.key for p in state.participants]
    if len(set(keys)) != len(keys):
        problems.append("duplicate participant key")

    seen_names: set[str] = set()
    for person in state.participants:
        folded = person.display_name.strip().lower()
        if folded in seen_names:
            problems.append(f"duplicate person name: {person.display_name}")
        seen_names.add(folded)

    kinds = {line.line_id: line.kind for line in state.content.lines}
    known_keys = set(keys)
    unknown_person_reported = False
    for line_id, assignees in state.assignments.items():
        if kinds.get(line_id) not in ASSIGNABLE_KINDS:
            problems.append(f"tag on unknown or non-item line: {line_id}")
        if not assignees or len(set(assignees)) != len(assignees):
            problems.append(f"empty or duplicate tag list: {line_id}")
        if not unknown_person_reported and any(key not in known_keys for key in assignees):
            problems.append("tag references unknown person")
            unknown_person_reported = True

    if not problems and len(json.dumps(_state_json(state)).encode()) > MAX_STATE_BYTES:
        problems.append("receipt too large")

    if problems:
        raise ReceiptValidationError(problems)


def compute_allocation(
    state: ReceiptState,
) -> tuple[AllocationResult | None, AllocationProblem | None]:
    """Run the allocator. Allocation errors (normal mid-edit) come back as data, not exceptions."""
    inp = AllocationInput(
        receipt=state.content,
        participant_ids=[p.key for p in state.participants],
        assignments={line_id: list(keys) for line_id, keys in state.assignments.items()},
    )
    try:
        return allocate(inp), None
    except AllocationError as exc:
        return None, AllocationProblem(code=exc.code, detail=exc.detail)


def _live(receipt_id: UUID) -> ColumnElement[bool]:
    return and_(Receipt.id == receipt_id, Receipt.expires_at > func.clock_timestamp())


def create_receipt(session: Session, *, example: bool) -> Receipt:
    purge_expired(session)
    live_count = session.scalar(
        select(func.count()).select_from(Receipt).where(Receipt.expires_at > func.clock_timestamp())
    )
    if (live_count or 0) >= MAX_LIVE_RECEIPTS:
        raise ServiceBusy

    receipt = Receipt(is_example=example, expires_at=func.clock_timestamp() + UNSAVED_RECEIPT_TTL)
    if example:
        state = _state_json(EXAMPLE_STATE)
        receipt.content = state["content"]  # type: ignore[assignment]
        receipt.participants = state["participants"]  # type: ignore[assignment]
        receipt.assignments = state["assignments"]  # type: ignore[assignment]
    session.add(receipt)
    session.commit()
    session.refresh(receipt)
    return receipt


def get_receipt(session: Session, receipt_id: UUID) -> Receipt:
    receipt = session.scalars(select(Receipt).where(_live(receipt_id))).one_or_none()
    if receipt is None:
        raise ReceiptNotFound
    return receipt


def save_receipt(session: Session, receipt_id: UUID, state: ReceiptState) -> Receipt:
    """Replace the receipt's state (last writer wins) and renew its expiry.

    One ``UPDATE ... RETURNING`` rather than SELECT-then-flush, so a DELETE or purge that commits
    in between yields ``ReceiptNotFound`` instead of a ``StaleDataError`` 500.
    """
    validate_state(state)
    dumped = _state_json(state)
    statement = (
        update(Receipt)
        .where(_live(receipt_id))
        .values(
            content=dumped["content"],
            participants=dumped["participants"],
            assignments=dumped["assignments"],
            expires_at=func.clock_timestamp() + RECEIPT_TTL,
            updated_at=func.clock_timestamp(),
        )
        .returning(Receipt)
        .execution_options(populate_existing=True, synchronize_session=False)
    )
    receipt = session.scalars(statement).one_or_none()
    if receipt is None:
        raise ReceiptNotFound  # nothing was written; the request's session closes it
    session.commit()
    return receipt


def delete_receipt(session: Session, receipt_id: UUID) -> None:
    result = session.execute(delete(Receipt).where(_live(receipt_id)))
    if not getattr(result, "rowcount", 0):
        session.rollback()
        raise ReceiptNotFound
    session.commit()


def to_response(receipt: Receipt) -> ReceiptResponse:
    """Re-validate the stored JSON and attach the computed allocation."""
    state = ReceiptState.model_validate(
        {
            "content": receipt.content,
            "participants": receipt.participants,
            "assignments": receipt.assignments,
        }
    )
    allocation, problem = compute_allocation(state)
    return ReceiptResponse(
        content=state.content,
        participants=state.participants,
        assignments=state.assignments,
        id=receipt.id,
        is_example=receipt.is_example,
        updated_at=receipt.updated_at,
        expires_at=receipt.expires_at,
        allocation=allocation,
        allocation_problem=problem,
    )
