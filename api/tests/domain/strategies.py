"""Hypothesis strategies that construct only *valid* allocation inputs (no ``assume`` filtering).

Validity is guaranteed by construction: targeted discounts never exceed their target's remaining
net, receipt-level discounts never exceed the total of item nets, and every assignable line is
assigned to at least one participant.
"""

from typing import Any
from uuid import UUID

from hypothesis import strategies as st

from app.domain.allocation import AllocationInput
from app.domain.receipt import ParsedReceipt

TAXABLE = st.sampled_from([True, False, None])


def _cents(max_value: int) -> st.SearchStrategy[int]:
    """Cents biased toward 0 so zero-base fallback paths (all-zero weights) get exercised."""
    return st.one_of(st.just(0), st.integers(min_value=0, max_value=max_value))


def _line(
    line_id: str, kind: str, total_cents: int, taxable: bool | None, **extra: Any
) -> dict[str, Any]:
    return {
        "line_id": line_id,
        "kind": kind,
        "name": line_id,
        "total_cents": total_cents,
        "taxable": taxable,
        **extra,
    }


@st.composite
def allocation_inputs(draw: st.DrawFn) -> AllocationInput:
    participant_count = draw(st.integers(min_value=1, max_value=5))
    participant_ids = [UUID(int=i + 1) for i in range(participant_count)]

    line_count = draw(st.integers(min_value=1, max_value=30))
    lines: list[dict[str, Any]] = []
    remaining_net: dict[str, int] = {}
    assignments: dict[str, list[UUID]] = {}

    for index in range(line_count):
        line_id = f"L{index}"
        # The first line is always assignable so every input has at least one.
        kind = (
            "item"
            if index == 0
            else draw(st.sampled_from(["item", "item", "deposit", "fee", "discount"]))
        )
        if kind == "discount" and not remaining_net:
            kind = "item"

        if kind in ("item", "deposit"):
            total = draw(_cents(50_000))
            lines.append(_line(line_id, kind, total, draw(TAXABLE)))
            remaining_net[line_id] = total
            assignments[line_id] = draw(
                st.lists(st.sampled_from(participant_ids), min_size=1, max_size=participant_count)
            )
        elif kind == "fee":
            total = draw(_cents(5_000))
            lines.append(_line(line_id, "fee", total, draw(TAXABLE)))
        else:
            target = draw(st.sampled_from(sorted(remaining_net)))
            remaining = remaining_net[target]
            # Often discount the full remaining net, producing zero-net lines.
            amount = draw(
                st.one_of(st.just(remaining), st.integers(min_value=0, max_value=remaining))
            )
            remaining_net[target] -= amount
            lines.append(
                _line(line_id, "discount", -amount, draw(TAXABLE), discount_target_line_id=target)
            )

    budget = sum(remaining_net.values())
    for index in range(draw(st.integers(min_value=0, max_value=3))):
        amount = draw(st.integers(min_value=0, max_value=budget))
        budget -= amount
        lines.append(_line(f"R{index}", "discount", -amount, draw(TAXABLE)))

    tax_amounts = draw(st.lists(_cents(5_000), max_size=3))
    receipt = ParsedReceipt.model_validate(
        {
            "lines": lines,
            "tax_lines": [{"label": "TAX", "amount_cents": amount} for amount in tax_amounts],
        }
    )
    return AllocationInput(
        receipt=receipt, participant_ids=participant_ids, assignments=assignments
    )


@st.composite
def allocation_inputs_with_targeted_discount(draw: st.DrawFn) -> tuple[AllocationInput, str]:
    """A valid input plus one extra item ``TGT`` with a targeted discount ``TD`` smaller than it.

    Returns the input and the discount's ``line_id``.
    """
    base = draw(allocation_inputs())
    target_total = draw(st.integers(min_value=2, max_value=50_000))
    discount = draw(st.integers(min_value=1, max_value=target_total - 1))
    lines = [line.model_dump() for line in base.receipt.lines]
    lines.append(_line("TGT", "item", target_total, draw(TAXABLE)))
    lines.append(_line("TD", "discount", -discount, draw(TAXABLE), discount_target_line_id="TGT"))

    assignments = dict(base.assignments)
    assignments["TGT"] = draw(
        st.lists(
            st.sampled_from(base.participant_ids),
            min_size=1,
            max_size=len(base.participant_ids),
        )
    )
    receipt = ParsedReceipt.model_validate({**base.receipt.model_dump(), "lines": lines})
    return (
        AllocationInput(
            receipt=receipt, participant_ids=base.participant_ids, assignments=assignments
        ),
        "TD",
    )
