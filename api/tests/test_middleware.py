import json
from collections.abc import Iterator
from typing import Any

import pytest
from conftest import TEST_ORIGIN, ClientFactory

from app.middleware import MAX_BODY_BYTES

pytestmark = pytest.mark.db


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _state(n_lines: int, n_people: int, long_text: bool) -> dict[str, Any]:
    people = [_uuid(i) for i in range(n_people)]
    lines = [
        {
            "line_id": f"L{i}",
            "kind": "item",
            "raw_text": "R" * 200 if long_text else "",
            "name": "N" * 120 if long_text else f"Item {i}",
            "total_cents": 199,
        }
        for i in range(n_lines)
    ]
    return {
        "content": {"lines": lines, "tax_lines": []},
        "participants": [{"key": k, "display_name": f"P{i}"} for i, k in enumerate(people)],
        "assignments": {line["line_id"]: people for line in lines},
    }


def _new_receipt(client: Any) -> str:
    response = client.post("/v1/receipts", json={})
    assert response.status_code == 201
    receipt_id: str = response.json()["id"]
    return receipt_id


def test_chunked_body_over_limit_is_413_with_cors(api_client: ClientFactory) -> None:
    client = api_client()
    receipt_id = _new_receipt(client)

    def chunks() -> Iterator[bytes]:
        for _ in range(3):
            yield b"x" * (MAX_BODY_BYTES // 2)

    response = client.put(
        f"/v1/receipts/{receipt_id}",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "request too large"}
    assert response.headers["access-control-allow-origin"] == TEST_ORIGIN


def test_content_length_over_limit_is_413(api_client: ClientFactory) -> None:
    client = api_client()
    response = client.post(
        "/v1/receipts",
        content=b" " * (MAX_BODY_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "request too large"}


def test_maximal_state_passes_transport_and_gets_422_too_large(api_client: ClientFactory) -> None:
    state = _state(n_lines=300, n_people=20, long_text=True)
    assert len(json.dumps(state).encode()) < MAX_BODY_BYTES
    client = api_client()
    response = client.put(f"/v1/receipts/{_new_receipt(client)}", json=state)
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "receipt too large"


def test_realistic_large_receipt_saves(api_client: ClientFactory) -> None:
    client = api_client()
    response = client.put(
        f"/v1/receipts/{_new_receipt(client)}", json=_state(n_lines=60, n_people=6, long_text=True)
    )
    assert response.status_code == 200, response.text
    assert response.json()["allocation"]["computed_total_cents"] == 60 * 199


def test_body_limit_ignores_other_routes(api_client: ClientFactory) -> None:
    response = api_client().get("/healthz")
    assert response.status_code == 200
