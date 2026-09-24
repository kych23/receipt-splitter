from typing import Any
from uuid import UUID, uuid4

import pytest
from conftest import TEST_ORIGIN, ClientFactory, FakeClock
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.db.models import Receipt
from app.ratelimit import Bucket, RateLimits
from app.receipts.example import ALEX, JORDAN, SAM
from app.routes import receipts as receipts_routes

pytestmark = pytest.mark.db

A = "00000000-0000-4000-8000-00000000000a"
B = "00000000-0000-4000-8000-00000000000b"


def _body(
    lines: list[dict[str, Any]] | None = None,
    people: list[tuple[str, str]] | None = None,
    tags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    return {
        "content": {
            "lines": lines
            if lines is not None
            else [{"line_id": "L1", "kind": "item", "name": "Eggs", "total_cents": 1000}],
            "tax_lines": [],
        },
        "participants": [
            {"key": key, "display_name": name}
            for key, name in (people if people is not None else [(A, "Alex"), (B, "Sam")])
        ],
        "assignments": tags if tags is not None else {"L1": [A, B]},
    }


def _create(client: Any, example: bool = False) -> dict[str, Any]:
    response = client.post("/v1/receipts", json={"example": example})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _backdate(db_session: Session, receipt_id: str) -> None:
    db_session.execute(
        update(Receipt)
        .where(Receipt.id == UUID(receipt_id))
        .values(expires_at=text("clock_timestamp() - interval '1 minute'"))
    )
    db_session.flush()


def _assert_exclusive(body: dict[str, Any]) -> None:
    assert (body["allocation"] is None) != (body["allocation_problem"] is None)


# ---------------------------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------------------------


def test_create_empty(api_client: ClientFactory) -> None:
    body = _create(api_client())
    assert body["is_example"] is False
    assert body["content"]["lines"] == []
    assert body["participants"] == []
    assert body["allocation"] is None
    assert body["allocation_problem"]["code"] == "no_participants"
    _assert_exclusive(body)


def test_create_example_allocates_to_pinned_table(api_client: ClientFactory) -> None:
    body = _create(api_client(), example=True)
    assert body["is_example"] is True
    _assert_exclusive(body)
    totals = {
        UUID(p["participant_id"]): p["total_cents"] for p in body["allocation"]["participants"]
    }
    assert totals == {ALEX: 426, SAM: 1503, JORDAN: 1880}
    assert body["allocation"]["computed_total_cents"] == 3809


def test_get_returns_the_receipt(api_client: ClientFactory) -> None:
    client = api_client()
    created = _create(client, example=True)
    response = client.get(f"/v1/receipts/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_put_round_trips_and_moves_timestamps_later(api_client: ClientFactory) -> None:
    client = api_client()
    created = _create(client)
    body = _body()
    response = client.put(f"/v1/receipts/{created['id']}", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["content"]["lines"][0]["name"] == "Eggs"
    assert saved["assignments"] == body["assignments"]
    assert saved["expires_at"] > created["expires_at"]
    assert saved["updated_at"] > created["updated_at"]
    shares = sorted(p["total_cents"] for p in saved["allocation"]["participants"])
    assert shares == [500, 500]
    _assert_exclusive(saved)
    assert client.get(f"/v1/receipts/{created['id']}").json() == saved


def test_delete_then_404(api_client: ClientFactory) -> None:
    client = api_client()
    receipt_id = _create(client)["id"]
    response = client.delete(f"/v1/receipts/{receipt_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/v1/receipts/{receipt_id}").status_code == 404
    assert client.delete(f"/v1/receipts/{receipt_id}").status_code == 404


# ---------------------------------------------------------------------------------------------
# 404 / 422
# ---------------------------------------------------------------------------------------------


def test_unknown_id_is_404(api_client: ClientFactory) -> None:
    response = api_client().get(f"/v1/receipts/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "receipt not found"}


def test_expired_receipt_is_404_everywhere(api_client: ClientFactory, db_session: Session) -> None:
    client = api_client()
    receipt_id = _create(client)["id"]
    _backdate(db_session, receipt_id)
    assert client.get(f"/v1/receipts/{receipt_id}").status_code == 404
    assert client.put(f"/v1/receipts/{receipt_id}", json=_body()).status_code == 404
    assert client.delete(f"/v1/receipts/{receipt_id}").status_code == 404


def _assert_fastapi_422(response: Any, msg_fragment: str | None = None) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    for error in detail:
        assert {"loc", "msg", "type"} <= error.keys()
    if msg_fragment is not None:
        assert any(msg_fragment in error["msg"] for error in detail), detail


def test_malformed_id_is_422(api_client: ClientFactory) -> None:
    _assert_fastapi_422(api_client().get("/v1/receipts/not-a-uuid"))


INVALID_BODIES = {
    "duplicate-key": (
        _body(people=[(A, "Alex"), (A, "Sam")], tags={"L1": [A]}),
        "duplicate participant key",
    ),
    "duplicate-name": (_body(people=[(A, "Alex"), (B, "ALEX")]), "duplicate person name"),
    "tag-unknown-line": (_body(tags={"L9": [A]}), "tag on unknown or non-item line"),
    "empty-tag-list": (_body(tags={"L1": []}), "empty or duplicate tag list"),
    "duplicate-tag": (_body(tags={"L1": [A, A]}), "empty or duplicate tag list"),
    "unknown-person": (_body(tags={"L1": [str(uuid4())]}), "tag references unknown person"),
    "blank-name": (_body(people=[(A, "   ")], tags={}), None),
    "extra-field": ({**_body(), "payer": A}, None),
}


@pytest.mark.parametrize(("body", "msg"), INVALID_BODIES.values(), ids=INVALID_BODIES.keys())
def test_put_validation_errors_are_422(
    api_client: ClientFactory, body: dict[str, Any], msg: str | None
) -> None:
    client = api_client()
    receipt_id = _create(client)["id"]
    response = client.put(f"/v1/receipts/{receipt_id}", json=body)
    _assert_fastapi_422(response, msg)
    if msg is not None:
        assert response.json()["detail"][0]["loc"] == ["body"]


def test_rejected_save_leaves_receipt_unchanged(api_client: ClientFactory) -> None:
    client = api_client()
    created = _create(client, example=True)
    client.put(f"/v1/receipts/{created['id']}", json=_body(tags={"L9": [A]}))
    assert client.get(f"/v1/receipts/{created['id']}").json() == created


# ---------------------------------------------------------------------------------------------
# 413 / 429 / 500 / 503 carry CORS headers
# ---------------------------------------------------------------------------------------------


def test_body_over_one_mib_is_413_with_cors(api_client: ClientFactory) -> None:
    client = api_client()
    receipt_id = _create(client)["id"]
    response = client.put(
        f"/v1/receipts/{receipt_id}",
        content=b"x" * (1_048_576 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "request too large"}
    assert response.headers["access-control-allow-origin"] == TEST_ORIGIN


def test_create_rate_limited_with_cors_and_retry_after(api_client: ClientFactory) -> None:
    client = api_client(rate_limits=RateLimits(create=Bucket(1, 3600)), clock=FakeClock())
    _create(client)
    response = client.post("/v1/receipts", json={})
    assert response.status_code == 429
    assert response.json() == {"detail": "too many requests"}
    assert response.headers["retry-after"] == "3600"
    assert response.headers["access-control-allow-origin"] == TEST_ORIGIN
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()


def test_put_rate_limited_per_receipt(api_client: ClientFactory) -> None:
    clock = FakeClock()
    client = api_client(rate_limits=RateLimits(per_receipt=Bucket(1, 3600)), clock=clock)
    first, second = _create(client)["id"], _create(client)["id"]
    assert client.put(f"/v1/receipts/{first}", json=_body()).status_code == 200
    limited = client.put(f"/v1/receipts/{first}", json=_body())
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3600"
    assert limited.headers["access-control-allow-origin"] == TEST_ORIGIN
    assert client.put(f"/v1/receipts/{second}", json=_body()).status_code == 200
    clock.now += 3600
    assert client.put(f"/v1/receipts/{first}", json=_body()).status_code == 200


def test_unhandled_error_is_json_500_with_cors(
    api_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("secret-detail")

    monkeypatch.setattr(receipts_routes, "get_receipt", boom)
    response = api_client().get(f"/v1/receipts/{uuid4()}")
    assert response.status_code == 500
    assert response.json() == {"detail": "internal error"}
    assert "secret-detail" not in response.text
    assert response.headers["access-control-allow-origin"] == TEST_ORIGIN


def test_create_at_capacity_is_503_with_cors(
    api_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.receipts import service

    client = api_client()
    monkeypatch.setattr(service, "MAX_LIVE_RECEIPTS", 0)
    response = client.post("/v1/receipts", json={})
    assert response.status_code == 503
    assert response.json() == {"detail": "busy, try again later"}
    assert response.headers["access-control-allow-origin"] == TEST_ORIGIN
