from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import ArgumentError, OperationalError

from app.config import Settings, get_settings
from app.db.session import get_database_check
from app.main import create_app

PLACEHOLDER_URL = "postgresql+psycopg://localhost/unused"
MISSING_DB_URL = "postgresql+psycopg://localhost/receipt_splitter_missing_test"


@pytest.fixture
def app_and_client() -> Iterator[tuple[FastAPI, TestClient]]:
    app = create_app(Settings(_env_file=None, database_url=PLACEHOLDER_URL, environment="local"))
    with TestClient(app) as client:
        yield app, client
    app.dependency_overrides.clear()


def _override_check(app: FastAPI, check: Callable[[], None]) -> None:
    app.dependency_overrides[get_database_check] = lambda: check


def test_healthz_does_not_touch_database(app_and_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_and_client
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("secret-conn-detail")),
        ArgumentError("secret-conn-detail"),
    ],
    ids=["operational-error", "argument-error"],
)
def test_readyz_returns_503_without_leaking_details(
    app_and_client: tuple[FastAPI, TestClient], error: Exception
) -> None:
    app, client = app_and_client

    def failing_check() -> None:
        raise error

    _override_check(app, failing_check)
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "error"}
    assert "secret-conn-detail" not in response.text


@pytest.mark.db
def test_readyz_ok_against_the_database_in_app_settings(
    migrated_engine: Engine, test_database_url: str
) -> None:
    app = create_app(Settings(_env_file=None, database_url=test_database_url, environment="local"))
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.db
def test_app_uses_its_own_settings_not_the_global_database_url(
    monkeypatch: pytest.MonkeyPatch, migrated_engine: Engine, test_database_url: str
) -> None:
    """Regression: the engine must come from create_app(settings), never from DATABASE_URL.

    The process-wide URL points at a reachable database, but the app is configured with a missing
    one, so a correctly isolated app reports 503.
    """
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    try:
        app = create_app(Settings(_env_file=None, database_url=MISSING_DB_URL, environment="local"))
        with TestClient(app) as client:
            response = client.get("/readyz")
    finally:
        get_settings.cache_clear()
    assert response.status_code == 503
