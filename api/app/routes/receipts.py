"""Receipt routes (docs/design/slice-3-manual-split.md, "Routes").

Possession of a receipt's random id is the only access control; ids never appear in URLs or the UI.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.receipts.schemas import (
    CreateReceiptRequest,
    ErrorResponse,
    ReceiptResponse,
    SaveReceiptRequest,
)
from app.receipts.service import (
    ReceiptNotFound,
    ReceiptValidationError,
    ServiceBusy,
    create_receipt,
    delete_receipt,
    get_receipt,
    save_receipt,
    to_response,
)

router = APIRouter(prefix="/v1/receipts", tags=["receipts"])

SessionDep = Annotated[Session, Depends(get_session)]

_COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    413: {"model": ErrorResponse, "description": "Request body too large"},
    429: {"model": ErrorResponse, "description": "Too many requests (see Retry-After)"},
    500: {"model": ErrorResponse, "description": "Internal error"},
}
_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Receipt not found or expired"}
}


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "receipt not found"})


def _validation_error(exc: ReceiptValidationError) -> RequestValidationError:
    return RequestValidationError(
        [{"loc": ("body",), "msg": problem, "type": "value_error"} for problem in exc.problems]
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ReceiptResponse,
    responses={
        **_COMMON_ERRORS,
        503: {"model": ErrorResponse, "description": "Live-receipt cap reached"},
    },
)
def create(body: CreateReceiptRequest, session: SessionDep) -> ReceiptResponse | JSONResponse:
    try:
        receipt = create_receipt(session, example=body.example)
    except ServiceBusy:
        return JSONResponse(status_code=503, content={"detail": "busy, try again later"})
    return to_response(receipt)


@router.get(
    "/{receipt_id}", response_model=ReceiptResponse, responses={**_COMMON_ERRORS, **_NOT_FOUND}
)
def read(receipt_id: UUID, session: SessionDep) -> ReceiptResponse | JSONResponse:
    try:
        return to_response(get_receipt(session, receipt_id))
    except ReceiptNotFound:
        return _not_found()


@router.put(
    "/{receipt_id}", response_model=ReceiptResponse, responses={**_COMMON_ERRORS, **_NOT_FOUND}
)
def save(
    receipt_id: UUID, body: SaveReceiptRequest, session: SessionDep
) -> ReceiptResponse | JSONResponse:
    try:
        return to_response(save_receipt(session, receipt_id, body))
    except ReceiptValidationError as exc:
        raise _validation_error(exc) from None
    except ReceiptNotFound:
        return _not_found()


@router.delete(
    "/{receipt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_COMMON_ERRORS, **_NOT_FOUND},
)
def remove(receipt_id: UUID, session: SessionDep) -> Response:
    try:
        delete_receipt(session, receipt_id)
    except ReceiptNotFound:
        return _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
