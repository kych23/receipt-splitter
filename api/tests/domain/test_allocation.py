from fractions import Fraction
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from strategies import allocation_inputs, allocation_inputs_with_targeted_discount

from app.domain.allocation import (
    AllocationError,
    AllocationInput,
    AllocationResult,
    AllocationWarning,
    ParticipantAllocation,
    allocate,
)
from app.domain.receipt import ParsedReceipt

A = UUID("00000000-0000-0000-0000-00000000000a")
B = UUID("00000000-0000-0000-0000-00000000000b")
C = UUID("00000000-0000-0000-0000-00000000000c")


def line(line_id: str, kind: str, total_cents: int, **extra: Any) -> dict[str, Any]:
    return {"line_id": line_id, "kind": kind, "name": "x", "total_cents": total_cents, **extra}


def run(
    participants: list[UUID],
    lines: list[dict[str, Any]],
    assignments: dict[str, list[UUID]],
    tax: list[int] | None = None,
) -> AllocationResult:
    receipt = ParsedReceipt.model_validate(
        {
            "lines": lines,
            "tax_lines": [{"label": "TAX", "amount_cents": amount} for amount in tax or []],
        }
    )
    return allocate(
        AllocationInput(receipt=receipt, participant_ids=participants, assignments=assignments)
    )


def row(result: AllocationResult, participant_id: UUID) -> ParticipantAllocation:
    return next(p for p in result.participants if p.participant_id == participant_id)


def shares(result: AllocationResult, line_id: str) -> dict[UUID, int]:
    return {
        p.participant_id: s.share_cents
        for p in result.participants
        for s in p.line_shares
        if s.line_id == line_id
    }


def test_e1_ny_tax_only_on_taxable_items() -> None:
    result = run(
        [A, B],
        [line("L1", "item", 6000, taxable=False), line("L2", "item", 2000, taxable=True)],
        {"L1": [A], "L2": [B]},
        tax=[160],
    )
    a, b = row(result, A), row(result, B)
    assert (a.tax_base_cents, a.tax_cents, a.total_cents) == (0, 0, 6000)
    assert (b.tax_base_cents, b.tax_cents, b.total_cents) == (2000, 160, 2160)
    assert result.computed_total_cents == 8160
    assert result.warnings == []


def test_e2_rotation_within_same_assignee_set() -> None:
    result = run(
        [A, B, C],
        [line("L1", "item", 1000), line("L2", "item", 1000)],
        {"L1": [A, B, C], "L2": [C, A, B]},
    )
    assert shares(result, "L1") == {A: 334, B: 333, C: 333}
    assert shares(result, "L2") == {A: 333, B: 334, C: 333}


def test_e2b_rotation_is_keyed_by_assignee_set() -> None:
    result = run(
        [A, B, C],
        [line("L1", "item", 101), line("L2", "item", 100), line("L3", "item", 101)],
        {"L1": [A, B], "L2": [C], "L3": [A, B]},
    )
    assert shares(result, "L1") == {A: 51, B: 50}
    assert shares(result, "L3") == {A: 50, B: 51}


def test_e3_targeted_discount_reduces_its_item() -> None:
    result = run(
        [A, B],
        [line("L1", "item", 500), line("D1", "discount", -100, discount_target_line_id="L1")],
        {"L1": [A, B]},
    )
    assert shares(result, "L1") == {A: 200, B: 200}
    assert row(result, A).receipt_discounts_cents == 0
    assert row(result, B).receipt_discounts_cents == 0
    assert result.computed_total_cents == 400


def test_e4_receipt_level_discount_is_proportional() -> None:
    result = run(
        [A, B],
        [line("L1", "item", 1000), line("L2", "item", 2000), line("D1", "discount", -300)],
        {"L1": [A], "L2": [B]},
    )
    assert row(result, A).receipt_discounts_cents == -100
    assert row(result, B).receipt_discounts_cents == -200


def test_e5_unknown_taxability_falls_back_to_proportional() -> None:
    result = run(
        [A, B],
        [line("L1", "item", 1000), line("L2", "item", 3000)],
        {"L1": [A], "L2": [B]},
        tax=[100],
    )
    assert (row(result, A).tax_cents, row(result, B).tax_cents) == (25, 75)
    assert result.warnings == [AllocationWarning.TAX_FALLBACK_PROPORTIONAL]


def test_e6_unknown_lines_treated_as_non_taxable_when_some_are_taxable() -> None:
    result = run(
        [A, B],
        [line("L1", "item", 1000, taxable=True), line("L2", "item", 1000)],
        {"L1": [A], "L2": [B]},
        tax=[80],
    )
    assert (row(result, A).tax_cents, row(result, B).tax_cents) == (80, 0)
    assert result.warnings == [AllocationWarning.UNKNOWN_TAXABILITY]


def test_e7_taxable_fee_forms_tax_base() -> None:
    result = run(
        [A, B],
        [
            line("L1", "item", 1000, taxable=False),
            line("L2", "item", 3000, taxable=False),
            line("F1", "fee", 10, taxable=True),
        ],
        {"L1": [A], "L2": [B]},
        tax=[1],
    )
    a, b = row(result, A), row(result, B)
    assert (a.fees_cents, b.fees_cents) == (3, 7)
    assert (a.tax_base_cents, b.tax_base_cents) == (3, 7)
    assert (a.tax_cents, b.tax_cents) == (0, 1)
    assert result.warnings == []


def test_e8_zero_tax_base_splits_equally_among_active_participants_only() -> None:
    result = run(
        [A, B, C],
        [
            line("L1", "item", 500, taxable=True),
            line("D1", "discount", -500, discount_target_line_id="L1"),
            line("L2", "item", 1000, taxable=False),
        ],
        {"L1": [A, B], "L2": [A]},
        tax=[5],
    )
    a, b, c = row(result, A), row(result, B), row(result, C)
    assert (a.tax_cents, b.tax_cents, c.tax_cents) == (3, 2, 0)
    assert (a.total_cents, b.total_cents, c.total_cents) == (1003, 2, 0)
    assert result.computed_total_cents == 1005
    assert result.warnings == [AllocationWarning.ZERO_BASE_EQUAL_SPLIT]


def test_e9_idle_participant_gets_zero_row() -> None:
    result = run([A, B, C], [line("L1", "item", 1000)], {"L1": [A]})
    c = row(result, C)
    assert c.line_shares == []
    assert (
        c.items_cents,
        c.receipt_discounts_cents,
        c.fees_cents,
        c.tax_base_cents,
        c.tax_cents,
        c.total_cents,
    ) == (0, 0, 0, 0, 0, 0)


def test_e10_all_non_taxable_lines_with_tax_warns() -> None:
    result = run(
        [A, B],
        [line("L1", "item", 1000, taxable=False), line("L2", "item", 3000, taxable=False)],
        {"L1": [A], "L2": [B]},
        tax=[100],
    )
    assert (row(result, A).tax_cents, row(result, B).tax_cents) == (25, 75)
    assert result.warnings == [AllocationWarning.TAX_WITHOUT_TAXABLE_LINES]


def test_e11_empty_receipt_returns_zero_rows() -> None:
    result = run([A], [], {})
    assert row(result, A).total_cents == 0
    assert result.computed_total_cents == 0
    assert result.warnings == []


def test_e11_empty_receipt_with_tax_is_an_error() -> None:
    with pytest.raises(AllocationError) as exc_info:
        run([A], [], {}, tax=[5])
    assert exc_info.value.code == "no_assignable_lines"


def test_e12_zero_total_taxable_line_does_not_switch_mode() -> None:
    result = run(
        [A, B],
        [line("L1", "item", 1000), line("L2", "item", 0, taxable=True)],
        {"L1": [A], "L2": [B]},
        tax=[10],
    )
    assert (row(result, A).tax_cents, row(result, B).tax_cents) == (10, 0)
    assert result.warnings == [AllocationWarning.TAX_FALLBACK_PROPORTIONAL]


def test_e13_fee_with_zero_item_base_splits_equally() -> None:
    result = run(
        [A, B],
        [
            line("L1", "item", 100),
            line("D1", "discount", -100, discount_target_line_id="L1"),
            line("F1", "fee", 5, taxable=False),
        ],
        {"L1": [A, B]},
    )
    assert (row(result, A).fees_cents, row(result, B).fees_cents) == (3, 2)
    assert result.warnings == [AllocationWarning.ZERO_BASE_EQUAL_SPLIT]


def test_printed_total_is_passed_through() -> None:
    receipt = ParsedReceipt.model_validate({"lines": [line("L1", "item", 100)], "total_cents": 999})
    result = allocate(
        AllocationInput(receipt=receipt, participant_ids=[A], assignments={"L1": [A]})
    )
    assert result.printed_total_cents == 999
    assert result.computed_total_cents == 100


ERROR_CASES: list[
    tuple[str, list[UUID], list[dict[str, Any]], dict[str, list[UUID]], list[int]]
] = [
    ("no_participants", [], [line("L1", "item", 100)], {"L1": [A]}, []),
    (
        "too_many_participants",
        [UUID(int=i) for i in range(1, 22)],
        [line("L1", "item", 100)],
        {"L1": [UUID(int=1)]},
        [],
    ),
    ("duplicate_participant", [A, B, A], [line("L1", "item", 100)], {"L1": [A]}, []),
    ("unknown_line", [A], [line("L1", "item", 100)], {"L1": [A], "ZZ": [A]}, []),
    (
        "assigned_non_assignable",
        [A],
        [line("L1", "item", 100), line("F1", "fee", 5)],
        {"L1": [A], "F1": [A]},
        [],
    ),
    ("empty_assignment", [A], [line("L1", "item", 100)], {"L1": []}, []),
    ("unknown_participant", [A], [line("L1", "item", 100)], {"L1": [B]}, []),
    ("unassigned_line", [A], [line("L1", "item", 100), line("L2", "item", 100)], {"L1": [A]}, []),
    (
        "negative_line_net",
        [A],
        [
            line("L1", "item", 100),
            line("D1", "discount", -150, discount_target_line_id="L1"),
        ],
        {"L1": [A]},
        [],
    ),
    ("no_assignable_lines", [A], [line("F1", "fee", 5)], {}, []),
    (
        "discount_exceeds_items",
        [A],
        [line("L1", "item", 100), line("D1", "discount", -101)],
        {"L1": [A]},
        [],
    ),
]


@pytest.mark.parametrize(
    ("code", "participants", "lines", "assignments", "tax"),
    [pytest.param(*case, id=case[0]) for case in ERROR_CASES],
)
def test_error_codes(
    code: str,
    participants: list[UUID],
    lines: list[dict[str, Any]],
    assignments: dict[str, list[UUID]],
    tax: list[int],
) -> None:
    with pytest.raises(AllocationError) as exc_info:
        run(participants, lines, assignments, tax=tax)
    assert exc_info.value.code == code


def test_precedence_unknown_line_before_unassigned_line() -> None:
    with pytest.raises(AllocationError) as exc_info:
        run([A], [line("L1", "item", 100), line("L2", "item", 100)], {"L1": [A], "ZZ": [A]})
    assert exc_info.value.code == "unknown_line"


def test_precedence_reports_first_offending_line_in_receipt_order() -> None:
    lines = [line(f"L{i}", "item", 100) for i in range(1, 6)]
    with pytest.raises(AllocationError) as exc_info:
        run([A], lines, {"L1": [A], "L3": [A], "L4": [A]})
    assert exc_info.value.code == "unassigned_line"
    assert "L2" in exc_info.value.detail
    assert "L5" not in exc_info.value.detail


def test_duplicate_assignees_are_deduplicated() -> None:
    result = run([A, B], [line("L1", "item", 100)], {"L1": [A, A, B]})
    assert shares(result, "L1") == {A: 50, B: 50}
    assert row(result, A).line_shares[0].split_count == 2


# ---------------------------------------------------------------------------------------------
# Property-based tests. Inputs are constructed valid, so any AllocationError is a failure.
# ---------------------------------------------------------------------------------------------


def _nets(inp: AllocationInput) -> dict[str, int]:
    nets = {
        ln.line_id: ln.total_cents for ln in inp.receipt.lines if ln.kind in ("item", "deposit")
    }
    for ln in inp.receipt.lines:
        if ln.discount_target_line_id is not None:
            nets[ln.discount_target_line_id] += ln.total_cents
    return nets


def _is_explicit_tax_mode(inp: AllocationInput) -> bool:
    return any(
        ln.kind != "discount" and ln.taxable is True and ln.total_cents > 0
        for ln in inp.receipt.lines
    )


@given(inp=allocation_inputs())
def test_p1_totals_sum_to_computed_total(inp: AllocationInput) -> None:
    result = allocate(inp)
    assert sum(p.total_cents for p in result.participants) == result.computed_total_cents


@given(inp=allocation_inputs())
def test_p2_line_shares_sum_to_net_and_differ_by_at_most_one_cent(inp: AllocationInput) -> None:
    result = allocate(inp)
    for line_id, net in _nets(inp).items():
        line_shares = [
            s.share_cents
            for p in result.participants
            for s in p.line_shares
            if s.line_id == line_id
        ]
        assert sum(line_shares) == net
        assert max(line_shares) - min(line_shares) <= 1


@given(inp=allocation_inputs())
def test_p3_all_tax_is_allocated(inp: AllocationInput) -> None:
    result = allocate(inp)
    assert sum(p.tax_cents for p in result.participants) == sum(
        t.amount_cents for t in inp.receipt.tax_lines
    )


@given(inp=allocation_inputs())
def test_p4_no_taxable_base_means_no_tax_in_explicit_mode(inp: AllocationInput) -> None:
    result = allocate(inp)
    if _is_explicit_tax_mode(inp) and sum(p.tax_base_cents for p in result.participants) > 0:
        for p in result.participants:
            if p.tax_base_cents == 0:
                assert p.tax_cents == 0


@given(inp=allocation_inputs(), data=st.data())
def test_p5_assignment_order_does_not_matter(inp: AllocationInput, data: st.DataObject) -> None:
    shuffled = {
        line_id: data.draw(st.permutations(ids)) for line_id, ids in inp.assignments.items()
    }
    variant = AllocationInput(
        receipt=inp.receipt, participant_ids=inp.participant_ids, assignments=shuffled
    )
    assert allocate(variant) == allocate(inp)


@given(inp=allocation_inputs())
def test_p6_no_negative_totals(inp: AllocationInput) -> None:
    for p in allocate(inp).participants:
        assert p.total_cents >= 0
        assert p.items_cents + p.receipt_discounts_cents >= 0


@given(inp=allocation_inputs())
def test_p7_zero_tax_means_zero_tax_everywhere(inp: AllocationInput) -> None:
    if sum(t.amount_cents for t in inp.receipt.tax_lines) == 0:
        assert all(p.tax_cents == 0 for p in allocate(inp).participants)


@given(inp=allocation_inputs())
def test_p8_proportional_components_are_within_rounding_bounds(inp: AllocationInput) -> None:
    result = allocate(inp)
    participants = result.participants
    tax_total = sum(t.amount_cents for t in inp.receipt.tax_lines)
    base_total = sum(p.tax_base_cents for p in participants)
    if inp.receipt.tax_lines and base_total > 0:
        for p in participants:
            expected = Fraction(tax_total * p.tax_base_cents, base_total)
            assert abs(p.tax_cents - expected) < len(inp.receipt.tax_lines)

    items_total = sum(p.items_cents for p in participants)
    if items_total > 0:
        receipt_discount = sum(
            ln.total_cents
            for ln in inp.receipt.lines
            if ln.kind == "discount" and ln.discount_target_line_id is None
        )
        fee_total = sum(ln.total_cents for ln in inp.receipt.lines if ln.kind == "fee")
        for p in participants:
            assert (
                abs(
                    p.receipt_discounts_cents
                    - Fraction(receipt_discount * p.items_cents, items_total)
                )
                < 1
            )
            assert abs(p.fees_cents - Fraction(fee_total * p.items_cents, items_total)) < 2


@given(inp=allocation_inputs())
def test_p9_idle_participants_owe_nothing(inp: AllocationInput) -> None:
    active = {pid for ids in inp.assignments.values() for pid in ids}
    for p in allocate(inp).participants:
        if p.participant_id not in active:
            assert p.line_shares == []
            assert (
                p.items_cents,
                p.receipt_discounts_cents,
                p.fees_cents,
                p.tax_base_cents,
                p.tax_cents,
                p.total_cents,
            ) == (0, 0, 0, 0, 0, 0)


@given(case=allocation_inputs_with_targeted_discount())
def test_p10_targeted_discount_equals_reducing_its_target(
    case: tuple[AllocationInput, str],
) -> None:
    inp, discount_id = case
    discount = next(ln for ln in inp.receipt.lines if ln.line_id == discount_id)
    target_id = discount.discount_target_line_id
    lines = []
    for ln in inp.receipt.lines:
        if ln.line_id == discount_id:
            continue
        if ln.line_id == target_id:
            ln = ln.model_copy(update={"total_cents": ln.total_cents + discount.total_cents})
        lines.append(ln)
    folded = AllocationInput(
        receipt=inp.receipt.model_copy(update={"lines": lines}),
        participant_ids=inp.participant_ids,
        assignments=inp.assignments,
    )
    assert allocate(folded).participants == allocate(inp).participants
