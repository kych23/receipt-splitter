"""Liveness (/healthz) and readiness (/readyz) probes. Responses expose no internal details."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import DatabaseCheck, SchemaNotCurrent, get_database_check

logger = logging.getLogger(__name__)

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "error"]


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/readyz",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
def readyz(
    check: Annotated[DatabaseCheck, Depends(get_database_check)],
) -> ReadyResponse | JSONResponse:
    try:
        check()
    except (SQLAlchemyError, SchemaNotCurrent):
        logger.warning("readiness check failed", exc_info=True)
        unavailable = ReadyResponse(status="unavailable", database="error")
        return JSONResponse(status_code=503, content=unavailable.model_dump())
    return ReadyResponse(status="ok", database="ok")
