from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.receipt import MAX_ABS_CENTS, ParsedReceipt


def _line(line_id: str, kind: str = "item", total_cents: Any = 100, **extra: Any) -> dict[str, Any]:
    return {"line_id": line_id, "kind": kind, "name": "x", "total_cents": total_cents, **extra}


def _receipt(*lines: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"lines": list(lines), **extra}


def test_accepts_every_line_kind_with_targeted_discount() -> None:
    receipt = ParsedReceipt.model_validate(
        _receipt(
            _line("L1", "item", 500, taxable=True, quantity=Decimal("0.73"), unit_price_cents=299),
            _line("D1", "discount", -100, discount_target_line_id="L1"),
            _line("D2", "discount", -50),
            _line("F1", "fee", 10, taxable=False),
            _line("B1", "deposit", 5),
            subtotal_cents=365,
            tax_lines=[{"label": "TAX", "amount_cents": 29}],
            total_cents=394,
            printed_item_count=2,
        )
    )
    kinds = [line.kind for line in receipt.lines]
    assert kinds == ["item", "discount", "discount", "fee", "deposit"]


# Each case names the error type or message fragment it must fail with, so a case can't pass
# because validation failed for some unrelated reason.
INVALID_RECEIPTS = [
    ("duplicate-line-id", _receipt(_line("L1"), _line("L1")), "duplicate line_id"),
    ("positive-discount", _receipt(_line("D1", "discount", 1)), "must have total_cents <= 0"),
    ("negative-item", _receipt(_line("L1", "item", -1)), "must have total_cents >= 0"),
    (
        "target-on-non-discount",
        _receipt(_line("L1"), _line("L2", discount_target_line_id="L1")),
        "only allowed on discount lines",
    ),
    (
        "missing-target",
        _receipt(_line("D1", "discount", -1, discount_target_line_id="NOPE")),
        "targets unknown line",
    ),
    (
        "target-is-discount",
        _receipt(
            _line("D1", "discount", -1),
            _line("D2", "discount", -1, discount_target_line_id="D1"),
        ),
        "must target an item or deposit line",
    ),
    (
        "target-is-fee",
        _receipt(_line("F1", "fee", 10), _line("D1", "discount", -1, discount_target_line_id="F1")),
        "must target an item or deposit line",
    ),
    ("extra-field", _receipt(_line("L1", foo="bar")), "extra_forbidden"),
    ("over-cap", _receipt(_line("L1", total_cents=MAX_ABS_CENTS + 1)), "less_than_equal"),
    (
        "quantity-too-precise",
        _receipt(_line("L1", quantity=Decimal("1.2345"))),
        "decimal_max_places",
    ),
    ("invalid-line-id", _receipt(_line("bad id")), "string_pattern_mismatch"),
    ("string-cents", _receipt(_line("L1", total_cents="123")), "int_type"),
    ("float-cents", _receipt(_line("L1", total_cents=12.0)), "int_type"),
]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [pytest.param(payload, reason, id=case_id) for case_id, payload, reason in INVALID_RECEIPTS],
)
def test_rejects_invalid_receipts(payload: dict[str, Any], reason: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ParsedReceipt.model_validate(payload)
    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert reason == errors[0]["type"] or reason in errors[0]["msg"]
