import logging
import threading
import uuid
from typing import Any

import pytest
from conftest import FakeClock
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.ratelimit import Bucket, RateLimiter, RateLimitMiddleware, RateLimits, client_key


def test_allows_capacity_then_limits_with_retry_after() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    bucket = Bucket(capacity=2, period_s=60)
    assert limiter.check("b", bucket, "k") is None
    assert limiter.check("b", bucket, "k") is None
    retry = limiter.check("b", bucket, "k")
    assert retry == pytest.approx(30.0)  # one token refills in 60/2 seconds


def test_refills_over_time() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    bucket = Bucket(capacity=1, period_s=10)
    assert limiter.check("b", bucket, "k") is None
    assert limiter.check("b", bucket, "k") is not None
    clock.now += 10
    assert limiter.check("b", bucket, "k") is None


def test_buckets_and_keys_are_independent() -> None:
    limiter = RateLimiter(clock=FakeClock())
    bucket = Bucket(capacity=1, period_s=60)
    assert limiter.check("create", bucket, "a") is None
    assert limiter.check("create", bucket, "b") is None
    assert limiter.check("other", bucket, "a") is None
    assert limiter.check("create", bucket, "a") is not None


def test_idle_keys_are_evicted_after_an_hour() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    bucket = Bucket(capacity=1, period_s=10_000)
    limiter.check("b", bucket, "old")
    clock.now += 3601
    limiter.check("b", bucket, "new")  # triggers the periodic sweep
    assert ("b", "old") not in limiter.tracked_keys()
    assert ("b", "new") in limiter.tracked_keys()


def test_key_count_is_capped_lru() -> None:
    limiter = RateLimiter(clock=FakeClock(), max_keys=3)
    bucket = Bucket(capacity=5, period_s=60)
    for key in ("a", "b", "c"):
        limiter.check("b", bucket, key)
    limiter.check("b", bucket, "a")  # a becomes most recently used
    limiter.check("b", bucket, "d")
    assert set(limiter.tracked_keys()) == {("b", "a"), ("b", "c"), ("b", "d")}


def test_concurrent_checks_consume_exactly_capacity() -> None:
    limiter = RateLimiter(clock=FakeClock())
    bucket = Bucket(capacity=50, period_s=10_000)
    allowed = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal allowed
        for _ in range(25):
            if limiter.check("b", bucket, "k") is None:
                with lock:
                    allowed += 1

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert allowed == 50


def _scope(client: tuple[str, int] | None, xff: str | None = None) -> dict[str, Any]:
    headers = [] if xff is None else [(b"x-forwarded-for", xff.encode())]
    return {"type": "http", "client": client, "headers": headers}


@pytest.mark.parametrize(
    ("hops", "xff", "expected"),
    [
        (0, "9.9.9.9", "10.0.0.1"),  # hops 0 ignores the header
        (1, "9.9.9.9", "9.9.9.9"),
        (1, "6.6.6.6, 9.9.9.9", "9.9.9.9"),  # spoofed left entry ignored
        (2, "6.6.6.6, 9.9.9.9, 8.8.8.8", "9.9.9.9"),
        (2, "9.9.9.9", "10.0.0.1"),  # short header falls back
        (1, "not-an-ip", "10.0.0.1"),  # invalid entry falls back
    ],
)
def test_client_ip_resolution(hops: int, xff: str, expected: str) -> None:
    assert client_key(_scope(("10.0.0.1", 1234), xff), hops) == expected


def test_ipv6_keyed_by_slash_64() -> None:
    a = client_key(_scope(("2001:db8:1:2::1", 1)), 0)
    b = client_key(_scope(("2001:db8:1:2:ffff::9", 1)), 0)
    c = client_key(_scope(("2001:db8:1:3::1", 1)), 0)
    assert a == b == "2001:db8:1:2::/64"
    assert c != a


def test_non_ip_and_missing_client() -> None:
    assert client_key(_scope(("testclient", 50000)), 0) == "testclient"
    assert client_key(_scope(None), 0) == "unknown"


# ---------------------------------------------------------------------------------------------
# RateLimitMiddleware (bare ASGI app: which bucket each request draws from)
# ---------------------------------------------------------------------------------------------

BIG = Bucket(1000, 3600)


def _ok(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _limited_client(limits: RateLimits, log_client_ip: bool = False, hops: int = 0) -> TestClient:
    app = Starlette(
        routes=[
            Route("/v1/receipts", _ok, methods=["POST"]),
            Route("/v1/receipts/{receipt_id}", _ok, methods=["GET", "PUT", "DELETE"]),
            Route("/healthz", _ok),
        ]
    )
    app.add_middleware(
        RateLimitMiddleware,
        limiter=RateLimiter(clock=FakeClock()),
        limits=limits,
        hops=hops,
        log_client_ip=log_client_ip,
    )
    return TestClient(app)


def test_create_bucket_keyed_by_client() -> None:
    client = _limited_client(RateLimits(create=Bucket(1, 3600), per_receipt=BIG, per_client=BIG))
    assert client.post("/v1/receipts").status_code == 200
    assert client.post("/v1/receipts").status_code == 429
    # Other clients and other receipt routes are unaffected.
    other = {"X-Forwarded-For": "9.9.9.9"}
    assert client.get("/v1/receipts/abc").status_code == 200
    hop_client = _limited_client(
        RateLimits(create=Bucket(1, 3600), per_receipt=BIG, per_client=BIG), hops=1
    )
    assert hop_client.post("/v1/receipts", headers=other).status_code == 200
    assert (
        hop_client.post("/v1/receipts", headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 200
    )
    assert hop_client.post("/v1/receipts", headers=other).status_code == 429


R1 = "11111111-1111-4111-8111-111111111111"
R2 = "22222222-2222-4222-8222-222222222222"


def test_per_receipt_bucket_keyed_by_path_id() -> None:
    client = _limited_client(RateLimits(create=BIG, per_receipt=Bucket(2, 3600), per_client=BIG))
    assert client.get(f"/v1/receipts/{R1}").status_code == 200
    assert client.put(f"/v1/receipts/{R1}").status_code == 200
    assert client.delete(f"/v1/receipts/{R1}").status_code == 429
    assert client.get(f"/v1/receipts/{R2}").status_code == 200


def test_other_spellings_of_an_id_share_its_bucket() -> None:
    client = _limited_client(RateLimits(create=BIG, per_receipt=Bucket(1, 3600), per_client=BIG))
    assert client.get(f"/v1/receipts/{R1}").status_code == 200
    for spelling in (R1.upper(), R1.replace("-", ""), f"{{{R1}}}"):
        assert client.get(f"/v1/receipts/{spelling}").status_code == 429


def test_junk_ids_create_no_buckets_and_cannot_refill_create() -> None:
    limits = RateLimits(create=Bucket(1, 3600), per_receipt=BIG, per_client=Bucket(10_000, 3600))
    app = Starlette(
        routes=[
            Route("/v1/receipts", _ok, methods=["POST"]),
            Route("/v1/receipts/{receipt_id}", _ok, methods=["GET"]),
        ]
    )
    limiter = RateLimiter(clock=FakeClock(), max_keys=5)
    app.add_middleware(RateLimitMiddleware, limiter=limiter, limits=limits, hops=0)
    client = TestClient(app)
    assert client.post("/v1/receipts").status_code == 200
    for i in range(20):
        client.get(f"/v1/receipts/junk-{i}")
        client.get(f"/v1/receipts/{uuid.UUID(int=i)}")  # valid ids churn only per_receipt
    assert not any(key.startswith("junk") for _, key in limiter.tracked_keys())
    assert client.post("/v1/receipts").status_code == 429


def test_create_is_keyed_by_ipv6_slash_48() -> None:
    limits = RateLimits(create=Bucket(1, 3600), per_receipt=BIG, per_client=BIG)
    client = _limited_client(limits, hops=1)
    first = {"X-Forwarded-For": "2001:db8:1:1::1"}
    same_48 = {"X-Forwarded-For": "2001:db8:1:ffff::1"}
    other_48 = {"X-Forwarded-For": "2001:db8:2::1"}
    assert client.post("/v1/receipts", headers=first).status_code == 200
    assert client.post("/v1/receipts", headers=same_48).status_code == 429
    assert client.post("/v1/receipts", headers=other_48).status_code == 200


def test_per_client_bucket_applies_to_every_receipt_request() -> None:
    client = _limited_client(RateLimits(create=BIG, per_receipt=BIG, per_client=Bucket(3, 3600)))
    for receipt_id in ("r1", "r2", "r3"):
        assert client.get(f"/v1/receipts/{receipt_id}").status_code == 200
    response = client.get("/v1/receipts/r4")
    assert response.status_code == 429
    assert response.json() == {"detail": "too many requests"}
    assert response.headers["retry-after"] == "1200"


def test_non_receipt_paths_are_not_limited() -> None:
    client = _limited_client(RateLimits(create=BIG, per_receipt=BIG, per_client=Bucket(1, 3600)))
    for _ in range(5):
        assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize("enabled", [True, False])
def test_client_ip_logged_only_when_enabled(
    caplog: pytest.LogCaptureFixture, enabled: bool
) -> None:
    client = _limited_client(RateLimits(), log_client_ip=enabled)
    with caplog.at_level(logging.INFO, logger="app.ratelimit"):
        client.get("/v1/receipts/a", headers={"X-Forwarded-For": "9.9.9.9"})
    logged = [r.getMessage() for r in caplog.records if r.name == "app.ratelimit"]
    if enabled:
        assert logged == ["rate-limit client key=testclient x-forwarded-for=9.9.9.9"]
    else:
        assert logged == []
