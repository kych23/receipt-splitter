"""Application settings loaded from environment variables (and ``api/.env`` locally)."""

import ipaddress
import re
from functools import lru_cache
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_BARE_POSTGRES_PREFIXES = ("postgres://", "postgresql://")
_PSYCOPG_PREFIX = "postgresql+psycopg://"
_SLUG_PATTERN = r"^[a-z0-9-]+$"
_DEFAULT_PORTS = {"http": 80, "https": 443}
_NUMERIC_HOST = re.compile(r"[0-9.]+")
_ASCII_HOST = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)*")


def normalize_database_url(url: str) -> str:
    """Force the psycopg 3 driver for bare Postgres URLs (Railway supplies ``postgres://``)."""
    for prefix in _BARE_POSTGRES_PREFIXES:
        if url.startswith(prefix):
            return _PSYCOPG_PREFIX + url.removeprefix(prefix)
    return url


def _canonical_host(hostname: str) -> str | None:
    """Host as a browser serializes it: compressed IPv6 in brackets, dotted-quad IPv4, or ASCII."""
    try:
        if ":" in hostname:
            return f"[{ipaddress.IPv6Address(hostname)}]"
        if _NUMERIC_HOST.fullmatch(hostname):
            return str(ipaddress.IPv4Address(hostname))  # rejects shorthand such as 127.1
    except ValueError:
        return None
    # Browsers send internationalized domains as punycode, so only ASCII labels can ever match.
    return hostname if _ASCII_HOST.fullmatch(hostname) else None


def _canonical_origin(origin: str) -> str | None:
    """Return the origin as a browser sends it (``scheme://host[:port]``), or None if invalid."""
    try:
        parts = urlsplit(origin)
        hostname = parts.hostname
        port = parts.port
    except ValueError:  # malformed brackets, non-numeric or out-of-range port
        return None
    default_port = _DEFAULT_PORTS.get(parts.scheme)
    if default_port is None or not hostname or port == 0:
        return None
    host = _canonical_host(hostname)
    if host is None:
        return None
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parts.scheme}://{host}{suffix}"


class Settings(BaseSettings):
    # hide_input_in_errors: validation errors must never echo DATABASE_URL (it holds a password).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: str
    # Required with no default: a missing ENVIRONMENT must never silently skip production guards.
    environment: Literal["local", "ci", "production"]
    cors_allowed_origins: Annotated[list[str], NoDecode] = []
    # Vercel preview deployments are allowed via a regex built from these validated slugs, never
    # from a free-form regex (which can be written to match any origin).
    vercel_preview_project: Annotated[str, Field(pattern=_SLUG_PATTERN)] | None = None
    vercel_team_slug: Annotated[str, Field(pattern=_SLUG_PATTERN)] | None = None
    # X-Forwarded-For entries appended by trusted proxies (Railway's edge = 1). 0 = use the socket.
    rate_limit_trusted_proxy_hops: Annotated[int, Field(ge=0, le=5)] = 0
    # Deploy-time verification only: log the resolved client key and raw X-Forwarded-For.
    rate_limit_log_client_ip: bool = False

    @property
    def cors_allowed_origin_regex(self) -> str | None:
        if self.vercel_preview_project is None or self.vercel_team_slug is None:
            return None
        project = re.escape(self.vercel_preview_project)
        team = re.escape(self.vercel_team_slug)
        return rf"^https://{project}-[a-z0-9-]+-{team}\.vercel\.app$"

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        normalized = normalize_database_url(value)
        try:
            url = make_url(normalized)
            # Accessing .port forces parsing of the port, which raises ValueError if non-numeric.
            _ = url.port
        except (ArgumentError, ValueError):
            raise ValueError("invalid DATABASE_URL") from None
        # Only Postgres via psycopg 3 is supported; anything else would fail at request time.
        if (url.get_backend_name(), url.get_driver_name()) != ("postgresql", "psycopg"):
            raise ValueError("invalid DATABASE_URL")
        return normalized

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        # CORSMiddleware compares the browser's Origin header by exact string. Browsers send the
        # canonical form, so any other spelling (trailing slash, uppercase, :443, userinfo...) would
        # silently never match. Require each entry to already be canonical; fail at startup if not.
        for origin in origins:
            if origin != "*" and _canonical_origin(origin) != origin:
                raise ValueError(f"invalid CORS_ALLOWED_ORIGINS entry: {origin!r}")
        return origins

    @model_validator(mode="after")
    def _validate_cors(self) -> Self:
        if (self.vercel_preview_project is None) != (self.vercel_team_slug is None):
            raise ValueError("VERCEL_PREVIEW_PROJECT and VERCEL_TEAM_SLUG must be set together")
        if self.environment == "production" and "*" in self.cors_allowed_origins:
            raise ValueError("CORS wildcard not allowed in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
