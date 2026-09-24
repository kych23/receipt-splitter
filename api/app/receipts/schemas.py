"""API models for the receipt resource (docs/design/slice-3-manual-split.md, "API schemas")."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.allocation import AllocationErrorCode, AllocationResult
from app.domain.receipt import ParsedReceipt

NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Participant(_Strict):
    key: UUID
    display_name: NameStr


class ReceiptState(_Strict):
    content: ParsedReceipt
    # List order is display order.
    participants: Annotated[list[Participant], Field(max_length=20)]
    # line_id -> participant keys
    assignments: dict[str, list[UUID]]


class CreateReceiptRequest(_Strict):
    example: bool = False


class SaveReceiptRequest(ReceiptState):
    pass


class AllocationProblem(_Strict):
    code: AllocationErrorCode
    detail: str


class ReceiptResponse(ReceiptState):
    id: UUID
    is_example: bool
    updated_at: datetime
    expires_at: datetime
    # Exactly one of these two is non-null.
    allocation: AllocationResult | None
    allocation_problem: AllocationProblem | None


class ErrorResponse(_Strict):
    detail: str
