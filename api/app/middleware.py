"""ASGI middleware for the receipt routes (docs/design/slice-3-manual-split.md, "Middleware order").

Both sit *inside* CORSMiddleware so their error responses still carry CORS headers; otherwise the
browser would report a 413 or 500 as a network failure.
"""

import logging

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.ratelimit import RECEIPTS_PREFIX, send_json

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_048_576  # transport limit; the stored-state limit is lower (service)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in ("POST", "PUT")
            or not scope.get("path", "").startswith(RECEIPTS_PREFIX)
        ):
            await self.app(scope, receive, send)
            return

        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await send_json(send, 413, {"detail": "request too large"})
                    return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI re-raises HTTPException from body reading (any other exception
                    # would become a 400 "error parsing the body").
                    raise HTTPException(status_code=413, detail="request too large")
            return message

        await self.app(scope, limited_receive, send)


class JsonErrorMiddleware:
    """Turn any unhandled exception into a JSON 500 that still passes through CORS."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            logger.exception("unhandled error on %s %s", scope["method"], scope.get("path"))
            if started:
                raise
            await send_json(send, 500, {"detail": "internal error"})
