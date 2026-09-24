"""In-process token-bucket rate limiting for the receipt routes.

See docs/design/slice-3-manual-split.md ("Rate limiting"). State lives in this process only, which
is correct for Railway's single replica. Routes run in a threadpool, so all state is lock-guarded.
"""

import ipaddress
import json
import logging
import math
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

RECEIPTS_PREFIX = "/v1/receipts"
_RECEIPT_ID_PATH = re.compile(r"^/v1/receipts/([^/]+)/?$")
_SWEEP_EVERY_S = 60.0
_IDLE_AFTER_S = 3600.0
# IPv6 clients usually hold a whole /64 (or much more), so they are keyed by network, not address.
# Receipt creation uses the wider /48 so one allocation can't mint thousands of create buckets.
CLIENT_IPV6_PREFIX = 64
CREATE_IPV6_PREFIX = 48


@dataclass(frozen=True)
class Bucket:
    capacity: int
    period_s: float  # time for an empty bucket to refill completely

    @property
    def rate_per_s(self) -> float:
        return self.capacity / self.period_s


@dataclass(frozen=True)
class RateLimits:
    create: Bucket = Bucket(30, 3600)  # POST /v1/receipts, keyed by client key
    per_receipt: Bucket = Bucket(1200, 3600)  # GET/PUT/DELETE /v1/receipts/{id}, keyed by id
    per_client: Bucket = Bucket(20_000, 3600)  # every /v1/receipts* request, keyed by client key


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000) -> None:
        self._clock = clock
        self._max_keys = max_keys  # per bucket name, so one bucket's churn can't evict another's
        self._lock = threading.Lock()
        # bucket_name -> key -> (tokens, last_update); each ordered by recency of use.
        self._state: dict[str, OrderedDict[str, tuple[float, float]]] = {}
        self._last_sweep = clock()

    def tracked_keys(self) -> Iterable[tuple[str, str]]:
        with self._lock:
            return [(name, key) for name, keys in self._state.items() for key in keys]

    def check(self, bucket_name: str, bucket: Bucket, client_key: str) -> float | None:
        """Consume one token. Returns None if allowed, else seconds until a token is available."""
        with self._lock:
            now = self._clock()
            self._sweep(now)
            keys = self._state.setdefault(bucket_name, OrderedDict())
            tokens, last = keys.get(client_key, (float(bucket.capacity), now))
            tokens = min(float(bucket.capacity), tokens + (now - last) * bucket.rate_per_s)
            keys[client_key] = (tokens, now)
            keys.move_to_end(client_key)
            while len(keys) > self._max_keys:
                keys.popitem(last=False)
            if tokens >= 1.0:
                keys[client_key] = (tokens - 1.0, now)
                return None
            return (1.0 - tokens) / bucket.rate_per_s

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < _SWEEP_EVERY_S:
            return
        self._last_sweep = now
        for keys in self._state.values():
            stale = [key for key, (_, last) in keys.items() if now - last > _IDLE_AFTER_S]
            for key in stale:
                del keys[key]


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return bytes(value).decode("latin-1")
    return None


def client_key(scope: Scope, hops: int, ipv6_prefix: int = CLIENT_IPV6_PREFIX) -> str:
    """Resolve the caller's rate-limit key: client IP (IPv6 by network), or a fallback string."""
    client = scope.get("client")
    raw: str | None = client[0] if client else None
    if hops > 0:
        forwarded = _header(scope, b"x-forwarded-for")
        entries = [e.strip() for e in forwarded.split(",")] if forwarded else []
        if len(entries) >= hops:
            candidate = entries[-hops]
            try:
                ipaddress.ip_address(candidate)
                raw = candidate
            except ValueError:
                pass
    if raw is None:
        return "unknown"
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return raw
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/{ipv6_prefix}", strict=False))
    return str(address)


def _canonical_receipt_id(segment: str) -> str | None:
    try:
        return str(uuid.UUID(segment))
    except ValueError:
        return None


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        limiter: RateLimiter,
        limits: RateLimits,
        hops: int,
        log_client_ip: bool = False,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.limits = limits
        self.hops = hops
        self.log_client_ip = log_client_ip

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith(RECEIPTS_PREFIX):
            await self.app(scope, receive, send)
            return

        key = client_key(scope, self.hops)
        if self.log_client_ip:
            logger.info(
                "rate-limit client key=%s x-forwarded-for=%s",
                key,
                _header(scope, b"x-forwarded-for"),
            )

        retry_after = self.limiter.check("per_client", self.limits.per_client, key)
        if retry_after is None:
            match = _RECEIPT_ID_PATH.match(path)
            if scope["method"] == "POST" and match is None:
                create_key = client_key(scope, self.hops, CREATE_IPV6_PREFIX)
                retry_after = self.limiter.check("create", self.limits.create, create_key)
            elif match is not None:
                receipt_key = _canonical_receipt_id(match.group(1))
                # Unparseable ids get no bucket (the route answers 422), so junk ids can't
                # create entries; spellings of one UUID share a bucket.
                if receipt_key is not None:
                    retry_after = self.limiter.check(
                        "per_receipt", self.limits.per_receipt, receipt_key
                    )

        if retry_after is not None:
            await send_json(
                send,
                429,
                {"detail": "too many requests"},
                extra_headers=[(b"retry-after", str(math.ceil(retry_after)).encode())],
            )
            return
        await self.app(scope, receive, send)


async def send_json(
    send: Send,
    status: int,
    payload: dict[str, object],
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(payload).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        *(extra_headers or []),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
