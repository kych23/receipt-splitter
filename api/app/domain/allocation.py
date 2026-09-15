"""Split a parsed receipt into exact per-participant totals, in integer cents.

Items and deposits are assigned to participants and split evenly among their assignees.
Receipt-level discounts and fees are shared in proportion to each participant's item
subtotal. Tax is shared in proportion to each participant's *taxable* subtotal when the
receipt marks taxable lines, otherwise proportionally to everything (with a warning).
Every zero-base fallback splits only among participants who were assigned at least one line.
"""

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.money import allocate_proportionally, split_evenly
from app.domain.receipt import ASSIGNABLE_KINDS, ParsedReceipt, ReceiptLine

ALLOCATOR_VERSION = "1"
MAX_PARTICIPANTS = 20


class AllocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt: ParsedReceipt
    participant_ids: list[UUID]
    assignments: dict[str, list[UUID]]


class LineShare(BaseModel):
    line_id: str
    share_cents: int
    split_count: int


class ParticipantAllocation(BaseModel):
    participant_id: UUID
    line_shares: list[LineShare]
    items_cents: int
    receipt_discounts_cents: int
    fees_cents: int
    tax_base_cents: int
    tax_cents: int
    total_cents: int


class AllocationWarning(StrEnum):
    TAX_FALLBACK_PROPORTIONAL = "tax_fallback_proportional"
    TAX_WITHOUT_TAXABLE_LINES = "tax_without_taxable_lines"
    UNKNOWN_TAXABILITY = "unknown_taxability"
    ZERO_BASE_EQUAL_SPLIT = "zero_base_equal_split"


class AllocationResult(BaseModel):
    allocator_version: str
    participants: list[ParticipantAllocation]
    computed_total_cents: int
    printed_total_cents: int | None
    warnings: list[AllocationWarning]


AllocationErrorCode = Literal[
    "no_participants",
    "too_many_participants",
    "duplicate_participant",
    "unknown_line",
    "assigned_non_assignable",
    "empty_assignment",
    "unknown_participant",
    "unassigned_line",
    "negative_line_net",
    "no_assignable_lines",
    "discount_exceeds_items",
]


class AllocationError(ValueError):
    """Invalid allocation input. ``detail`` always names the offending identifier(s)."""

    def __init__(self, code: AllocationErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class AllocationInvariantError(RuntimeError):
    """Internal arithmetic invariant violated — a programming bug, not bad input."""


@dataclass(frozen=True)
class _Validated:
    """Input after validation: assignees de-duplicated and ordered by participant position."""

    assignable: list[ReceiptLine]
    assignees: dict[str, list[UUID]]
    nets: dict[str, int]
    receipt_discount_cents: int


def allocate(inp: AllocationInput) -> AllocationResult:
    receipt = inp.receipt
    participant_ids = inp.participant_ids
    tax_total = sum(tax_line.amount_cents for tax_line in receipt.tax_lines)

    validated = _validate(inp, tax_total)
    if not validated.assignable:
        # Rule 10 guarantees every amount is zero here.
        return _zero_result(receipt, participant_ids)

    index_of = {participant_id: i for i, participant_id in enumerate(participant_ids)}
    count = len(participant_ids)
    active = [False] * count
    for ids in validated.assignees.values():
        for participant_id in ids:
            active[index_of[participant_id]] = True

    warnings: set[AllocationWarning] = set()

    def alloc_active(amount: int, weights: list[int]) -> list[int]:
        active_indices = [i for i in range(count) if active[i]]
        sub_weights = [weights[i] for i in active_indices]
        if amount != 0 and sum(sub_weights) == 0:
            warnings.add(AllocationWarning.ZERO_BASE_EQUAL_SPLIT)
        values = [0] * count
        for i, value in zip(
            active_indices, allocate_proportionally(amount, sub_weights), strict=True
        ):
            values[i] = value
        return values

    # Step 3: item shares, rotating extra cents within each distinct assignee set.
    line_shares: list[list[LineShare]] = [[] for _ in range(count)]
    items = [0] * count
    taxable_items = [0] * count
    rotation: defaultdict[frozenset[UUID], int] = defaultdict(int)
    for receipt_line in validated.assignable:
        ids = validated.assignees[receipt_line.line_id]
        key = frozenset(ids)
        offset = rotation[key] % len(ids)
        rotation[key] += 1
        net = validated.nets[receipt_line.line_id]
        for participant_id, share in zip(ids, split_evenly(net, len(ids), offset), strict=True):
            i = index_of[participant_id]
            line_shares[i].append(
                LineShare(line_id=receipt_line.line_id, share_cents=share, split_count=len(ids))
            )
            items[i] += share
            if receipt_line.taxable is True:
                taxable_items[i] += share

    # Step 4: receipt-level discounts.
    receipt_discounts = alloc_active(validated.receipt_discount_cents, items)

    # Step 5: fees, with taxable fees tracked separately for the tax base.
    fee_lines = [ln for ln in receipt.lines if ln.kind == "fee"]
    taxable_fee_total = sum(ln.total_cents for ln in fee_lines if ln.taxable is True)
    other_fee_total = sum(ln.total_cents for ln in fee_lines if ln.taxable is not True)
    taxable_fees = alloc_active(taxable_fee_total, items)
    other_fees = alloc_active(other_fee_total, items)
    fees = [t + o for t, o in zip(taxable_fees, other_fees, strict=True)]

    # Step 6: tax mode and base.
    tax_lines_considered = [ln for ln in receipt.lines if ln.kind != "discount"]
    explicit = any(ln.taxable is True and ln.total_cents > 0 for ln in tax_lines_considered)
    has_unknown = any(ln.taxable is None for ln in tax_lines_considered)
    if explicit:
        base = [ti + tf for ti, tf in zip(taxable_items, taxable_fees, strict=True)]
        if tax_total > 0 and has_unknown:
            warnings.add(AllocationWarning.UNKNOWN_TAXABILITY)
    else:
        base = [it + fe for it, fe in zip(items, fees, strict=True)]
        if tax_total > 0:
            warnings.add(
                AllocationWarning.TAX_FALLBACK_PROPORTIONAL
                if has_unknown
                else AllocationWarning.TAX_WITHOUT_TAXABLE_LINES
            )

    # Step 7: tax, one allocation per printed tax line.
    tax = [0] * count
    for tax_line in receipt.tax_lines:
        for i, value in enumerate(alloc_active(tax_line.amount_cents, base)):
            tax[i] += value

    # Step 8: totals and invariants.
    participants: list[ParticipantAllocation] = []
    for i, participant_id in enumerate(participant_ids):
        total = items[i] + receipt_discounts[i] + fees[i] + tax[i]
        if total < 0:
            raise AllocationInvariantError(f"negative total for participant {participant_id}")
        participants.append(
            ParticipantAllocation(
                participant_id=participant_id,
                line_shares=line_shares[i],
                items_cents=items[i],
                receipt_discounts_cents=receipt_discounts[i],
                fees_cents=fees[i],
                tax_base_cents=base[i] if active[i] else 0,
                tax_cents=tax[i],
                total_cents=total,
            )
        )

    computed_total = (
        sum(ln.total_cents for ln in validated.assignable)
        + sum(ln.total_cents for ln in receipt.lines if ln.kind == "discount")
        + sum(ln.total_cents for ln in fee_lines)
        + tax_total
    )
    allocated_total = sum(p.total_cents for p in participants)
    if allocated_total != computed_total:
        raise AllocationInvariantError(
            f"allocated {allocated_total} cents but receipt computes {computed_total}"
        )

    return AllocationResult(
        allocator_version=ALLOCATOR_VERSION,
        participants=participants,
        computed_total_cents=computed_total,
        printed_total_cents=receipt.total_cents,
        warnings=sorted(warnings),
    )


def _validate(inp: AllocationInput, tax_total: int) -> _Validated:
    """Apply validation rules one at a time; the first violated rule raises."""
    receipt = inp.receipt
    participant_ids = inp.participant_ids
    assignments = inp.assignments

    if not participant_ids:
        raise AllocationError("no_participants", "participant count is 0")
    if len(participant_ids) > MAX_PARTICIPANTS:
        raise AllocationError(
            "too_many_participants",
            f"participant count is {len(participant_ids)}, max is {MAX_PARTICIPANTS}",
        )
    seen: set[UUID] = set()
    for participant_id in participant_ids:
        if participant_id in seen:
            raise AllocationError(
                "duplicate_participant", f"participant_id={participant_id} appears twice"
            )
        seen.add(participant_id)

    lines_by_id = {ln.line_id: ln for ln in receipt.lines}
    unknown_keys = sorted(key for key in assignments if key not in lines_by_id)
    if unknown_keys:
        raise AllocationError("unknown_line", f"line_id={unknown_keys[0]} is not on the receipt")

    for ln in receipt.lines:
        if ln.line_id in assignments and ln.kind not in ASSIGNABLE_KINDS:
            raise AllocationError(
                "assigned_non_assignable", f"line_id={ln.line_id} is a {ln.kind} line"
            )

    assignable = [ln for ln in receipt.lines if ln.kind in ASSIGNABLE_KINDS]
    for ln in assignable:
        if ln.line_id in assignments and not assignments[ln.line_id]:
            raise AllocationError("empty_assignment", f"line_id={ln.line_id} has no assignees")

    position = {participant_id: i for i, participant_id in enumerate(participant_ids)}
    assignees: dict[str, list[UUID]] = {}
    for ln in assignable:
        if ln.line_id not in assignments:
            continue
        for participant_id in assignments[ln.line_id]:
            if participant_id not in position:
                raise AllocationError(
                    "unknown_participant",
                    f"line_id={ln.line_id} participant_id={participant_id} is not a participant",
                )
        assignees[ln.line_id] = sorted(set(assignments[ln.line_id]), key=position.__getitem__)

    for ln in assignable:
        if ln.line_id not in assignments:
            raise AllocationError("unassigned_line", f"line_id={ln.line_id} is not assigned")

    nets = {ln.line_id: ln.total_cents for ln in assignable}
    for ln in receipt.lines:
        if ln.discount_target_line_id is not None:
            nets[ln.discount_target_line_id] += ln.total_cents
    for ln in assignable:
        if nets[ln.line_id] < 0:
            raise AllocationError(
                "negative_line_net",
                f"line_id={ln.line_id} net is {nets[ln.line_id]} cents after discounts",
            )

    receipt_discount = sum(
        ln.total_cents
        for ln in receipt.lines
        if ln.kind == "discount" and ln.discount_target_line_id is None
    )
    if not assignable:
        other_amounts = [ln.total_cents for ln in receipt.lines]
        if tax_total != 0 or any(amount != 0 for amount in other_amounts):
            raise AllocationError(
                "no_assignable_lines",
                f"no item/deposit lines but fees/discounts/tax total "
                f"{sum(other_amounts) + tax_total} cents",
            )

    net_total = sum(nets.values())
    if -receipt_discount > net_total:
        raise AllocationError(
            "discount_exceeds_items",
            f"receipt-level discounts {receipt_discount} cents exceed item total {net_total} cents",
        )

    return _Validated(
        assignable=assignable,
        assignees=assignees,
        nets=nets,
        receipt_discount_cents=receipt_discount,
    )


def _zero_result(receipt: ParsedReceipt, participant_ids: list[UUID]) -> AllocationResult:
    return AllocationResult(
        allocator_version=ALLOCATOR_VERSION,
        participants=[
            ParticipantAllocation(
                participant_id=participant_id,
                line_shares=[],
                items_cents=0,
                receipt_discounts_cents=0,
                fees_cents=0,
                tax_base_cents=0,
                tax_cents=0,
                total_cents=0,
            )
            for participant_id in participant_ids
        ],
        computed_total_cents=0,
        printed_total_cents=receipt.total_cents,
        warnings=[],
    )
