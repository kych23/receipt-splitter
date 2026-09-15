"""Typed schema for a parsed receipt. All money is integer cents."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

MAX_ABS_CENTS = 10_000_000  # $100,000 sanity cap
LINE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

LineKind = Literal["item", "discount", "fee", "deposit"]
ASSIGNABLE_KINDS: frozenset[LineKind] = frozenset({"item", "deposit"})

Cents = Annotated[StrictInt, Field(ge=-MAX_ABS_CENTS, le=MAX_ABS_CENTS)]
NonNegativeCents = Annotated[StrictInt, Field(ge=0, le=MAX_ABS_CENTS)]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReceiptLine(_Frozen):
    line_id: Annotated[str, Field(pattern=LINE_ID_PATTERN)]
    kind: LineKind
    raw_text: Annotated[str, Field(max_length=200)] = ""
    name: Annotated[str, Field(min_length=1, max_length=120)]
    quantity: Annotated[Decimal, Field(gt=0, decimal_places=3)] | None = None
    unit_price_cents: NonNegativeCents | None = None
    total_cents: Cents
    taxable: bool | None = None
    tax_code: Annotated[str, Field(max_length=8)] | None = None
    discount_target_line_id: str | None = None

    @model_validator(mode="after")
    def _check_sign_and_target(self) -> Self:
        if self.kind == "discount":
            if self.total_cents > 0:
                raise ValueError(f"discount line {self.line_id} must have total_cents <= 0")
        else:
            if self.total_cents < 0:
                raise ValueError(f"{self.kind} line {self.line_id} must have total_cents >= 0")
            if self.discount_target_line_id is not None:
                raise ValueError(
                    f"discount_target_line_id is only allowed on discount lines ({self.line_id})"
                )
        return self


class TaxLine(_Frozen):
    label: Annotated[str, Field(min_length=1, max_length=40)]
    amount_cents: NonNegativeCents


class ParsedReceipt(_Frozen):
    merchant_name: Annotated[str, Field(max_length=120)] | None = None
    chain: Annotated[str, Field(max_length=60)] | None = None
    purchased_on: date | None = None
    currency: Literal["USD"] = "USD"
    lines: Annotated[list[ReceiptLine], Field(max_length=300)]
    subtotal_cents: NonNegativeCents | None = None
    tax_lines: Annotated[list[TaxLine], Field(max_length=5)] = []
    total_cents: NonNegativeCents | None = None
    printed_item_count: Annotated[StrictInt, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _check_line_references(self) -> Self:
        kinds_by_id: dict[str, LineKind] = {}
        for line in self.lines:
            if line.line_id in kinds_by_id:
                raise ValueError(f"duplicate line_id {line.line_id}")
            kinds_by_id[line.line_id] = line.kind

        for line in self.lines:
            target = line.discount_target_line_id
            if target is None:
                continue
            if target not in kinds_by_id:
                raise ValueError(f"discount {line.line_id} targets unknown line {target}")
            if kinds_by_id[target] not in ASSIGNABLE_KINDS:
                raise ValueError(
                    f"discount {line.line_id} must target an item or deposit line, not {target}"
                )
        return self
