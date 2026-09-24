import re
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings, normalize_database_url

DB_URL = "postgresql+psycopg://localhost/d"

# Settings read these from os.environ, which conftest fills from api/.env and the shell may export.
_SETTINGS_ENV_VARS = (
    "ENVIRONMENT",
    "CORS_ALLOWED_ORIGINS",
    "VERCEL_PREVIEW_PROJECT",
    "VERCEL_TEAM_SLUG",
    "RATE_LIMIT_TRUSTED_PROXY_HOPS",
    "RATE_LIMIT_LOG_CLIENT_IP",
)


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make_settings(**overrides: Any) -> Settings:
    """Settings built only from explicit values (the autouse fixture clears related env vars)."""
    values: dict[str, Any] = {"database_url": DB_URL, "environment": "local", **overrides}
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgresql+psycopg://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
    ],
)
def test_normalize_database_url(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected


def test_settings_normalizes_database_url() -> None:
    settings = make_settings(database_url="postgres://u:p@h:5432/d")
    assert settings.database_url == "postgresql+psycopg://u:p@h:5432/d"


def test_cors_origins_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", " https://a.com, https://b.com,, ")
    assert make_settings().cors_allowed_origins == ["https://a.com", "https://b.com"]


# Entries that could never equal a browser-sent Origin header (lowercase scheme/host, no default
# port, no path/query/fragment/userinfo), so CORS would silently fail for them.
MALFORMED_ORIGINS = {
    "trailing-slash": "https://receipt-splitter.vercel.app/",
    "path": "https://receipt-splitter.vercel.app/app",
    "query": "https://receipt-splitter.vercel.app?x=1",
    "empty-query": "https://app.example.com?",
    "empty-fragment": "https://app.example.com#",
    "no-scheme": "receipt-splitter.vercel.app",
    "bad-scheme": "ftp://example.com",
    "no-host": "https://",
    "uppercase-scheme": "HTTPS://app.example.com",
    "uppercase-host": "https://App.example.com",
    "default-https-port": "https://app.example.com:443",
    "default-http-port": "http://localhost:80",
    "bad-port": "https://app.example.com:abc",
    "out-of-range-port": "https://app.example.com:99999",
    "userinfo": "https://u@app.example.com",
    "unterminated-ipv6": "https://[::1",
    "bracketed-non-ip": "http://[notv6]:3000",
    "non-ascii-host": "https://bücher.de",
    "space-in-host": "http://app example.com",
    "non-compressed-ipv6": "http://[0:0:0:0:0:0:0:1]",
    "short-ipv4": "http://127.1",
    "port-zero": "https://a.com:0",
}


@pytest.mark.parametrize(
    "origin",
    [pytest.param(origin, id=case_id) for case_id, origin in MALFORMED_ORIGINS.items()],
)
def test_malformed_cors_origin_rejected(origin: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        make_settings(cors_allowed_origins=[origin])
    assert "invalid CORS_ALLOWED_ORIGINS entry" in str(exc_info.value)


def test_valid_cors_origins_accepted() -> None:
    origins = [
        "http://localhost:3000",
        "https://receipt-splitter.vercel.app",
        "https://app.example.com:8443",
        "http://[::1]:3000",
        "http://127.0.0.1:8000",
        "https://xn--bcher-kva.de",
    ]
    assert make_settings(cors_allowed_origins=origins).cors_allowed_origins == origins


def test_cors_wildcard_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        make_settings(environment="production", cors_allowed_origins=["*"])


def test_cors_wildcard_allowed_locally() -> None:
    assert make_settings(cors_allowed_origins=["*"]).cors_allowed_origins == ["*"]


def test_missing_database_url_names_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, environment="local")
    assert "database_url" in str(exc_info.value)


def test_environment_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ENVIRONMENT must fail loudly, never silently skip production-only guards."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, database_url=DB_URL)
    assert "environment" in str(exc_info.value)


def test_no_preview_regex_without_vercel_settings() -> None:
    assert make_settings().cors_allowed_origin_regex is None


def test_preview_regex_built_from_validated_slugs() -> None:
    settings = make_settings(
        environment="production",
        vercel_preview_project="receipt-splitter",
        vercel_team_slug="kyle-team",
    )
    regex = settings.cors_allowed_origin_regex
    assert regex is not None
    allowed = [
        "https://receipt-splitter-git-main-kyle-team.vercel.app",
        "https://receipt-splitter-abc123-kyle-team.vercel.app",
    ]
    rejected = [
        "https://evil.example",
        "https://x.vercel.app",
        "https://attacker.vercel.app",
        "https://receipt-splitter-abc-other-team.vercel.app",
        "http://receipt-splitter-abc-kyle-team.vercel.app",
        "https://receipt-splitter-abc-kyle-team.vercel.app.evil.example",
    ]
    for origin in allowed:
        assert re.fullmatch(regex, origin), origin
    for origin in rejected:
        assert not re.fullmatch(regex, origin), origin


@pytest.mark.parametrize(
    "overrides",
    [
        {"vercel_preview_project": "receipt-splitter"},
        {"vercel_team_slug": "kyle-team"},
        {"vercel_preview_project": ".*", "vercel_team_slug": "kyle-team"},
        {"vercel_preview_project": "receipt-splitter", "vercel_team_slug": "a|b"},
        {"vercel_preview_project": "Receipt_Splitter", "vercel_team_slug": "kyle-team"},
    ],
    ids=["project-only", "team-only", "regex-project", "regex-team", "invalid-chars"],
)
def test_invalid_vercel_preview_settings_rejected(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        make_settings(environment="production", **overrides)


@pytest.mark.parametrize(
    "bad_url",
    [
        "postgresql+psycopg://u:s3cret@h:abc/d",
        "not a url",
        "postgresql+psycopg2://u:s3cret@h/d",
        "sqlite:///x.db",
        "mysql://u:s3cret@h/d",
    ],
)
def test_malformed_database_url_rejected_without_echoing_secrets(bad_url: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        make_settings(database_url=bad_url)
    message = str(exc_info.value)
    assert "invalid DATABASE_URL" in message
    assert "s3cret" not in message


def test_rate_limit_hops_default_to_socket_address() -> None:
    assert make_settings().rate_limit_trusted_proxy_hops == 0


def test_rate_limit_hops_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    assert make_settings().rate_limit_trusted_proxy_hops == 1


@pytest.mark.parametrize("hops", [-1, 6])
def test_rate_limit_hops_out_of_range_rejected(hops: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(rate_limit_trusted_proxy_hops=hops)
