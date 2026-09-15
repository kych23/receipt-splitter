import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

LOCAL_ORIGIN = "http://localhost:3000"
PREVIEW_ORIGIN = "https://receipt-splitter-git-main-kyle-team.vercel.app"


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://localhost/unused",
        environment="production",
        cors_allowed_origins=[LOCAL_ORIGIN],
        vercel_preview_project="receipt-splitter",
        vercel_team_slug="kyle-team",
    )
    return TestClient(create_app(settings))


def _preflight(client: TestClient, origin: str) -> dict[str, str]:
    response = client.options(
        "/readyz", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )
    return dict(response.headers)


@pytest.mark.parametrize("origin", [LOCAL_ORIGIN, PREVIEW_ORIGIN])
def test_preflight_allows_configured_origins(client: TestClient, origin: str) -> None:
    assert _preflight(client, origin).get("access-control-allow-origin") == origin


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "https://attacker.vercel.app", "https://x.vercel.app"],
)
def test_preflight_rejects_unknown_origins(client: TestClient, origin: str) -> None:
    assert "access-control-allow-origin" not in _preflight(client, origin)


def test_simple_request_from_allowed_origin_gets_cors_header(client: TestClient) -> None:
    response = client.get("/healthz", headers={"Origin": LOCAL_ORIGIN})
    assert response.headers.get("access-control-allow-origin") == LOCAL_ORIGIN
