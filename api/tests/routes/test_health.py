from collections.abc import Callable, Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
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


@pytest.mark.db
def test_readyz_requires_the_schema_at_the_code_head(
    migrated_engine: Engine, alembic_config: Config, test_database_url: str
) -> None:
    """Regression: production ran for weeks with no tables while /readyz said ok (SELECT 1 only).

    Readiness must fail when migrations haven't run (or stopped early), so a deploy whose
    pre-deploy migration didn't run fails its healthcheck instead of going live.
    """
    app = create_app(Settings(_env_file=None, database_url=test_database_url, environment="local"))
    try:
        with TestClient(app) as client:
            command.downgrade(alembic_config, "base")  # alembic_version left empty
            assert client.get("/readyz").status_code == 503

            # The production incident: no tables at all, not even alembic_version.
            with migrated_engine.begin() as conn:
                conn.execute(text("DROP TABLE alembic_version"))
            response = client.get("/readyz")
            assert response.status_code == 503
            assert response.json() == {"status": "unavailable", "database": "error"}

            command.upgrade(alembic_config, "0001")  # known but older revision
            response = client.get("/readyz")
            assert response.status_code == 503
            assert response.json() == {"status": "unavailable", "database": "error"}

            command.upgrade(alembic_config, "head")
            assert client.get("/readyz").status_code == 200
    finally:
        command.upgrade(alembic_config, "head")


@pytest.mark.db
def test_readyz_accepts_a_newer_revision_than_the_code_knows(
    migrated_engine: Engine, test_database_url: str
) -> None:
    """Railway migrates while the old container still serves; expand → contract keeps it working."""
    with migrated_engine.begin() as conn:
        original = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        conn.execute(text("UPDATE alembic_version SET version_num = 'ffff_future'"))
    try:
        app = create_app(
            Settings(_env_file=None, database_url=test_database_url, environment="local")
        )
        with TestClient(app) as client:
            assert client.get("/readyz").status_code == 200
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": original})
