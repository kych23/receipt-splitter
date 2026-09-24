from collections.abc import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.logging_config import configure_logging
from app.middleware import BodySizeLimitMiddleware, JsonErrorMiddleware
from app.ratelimit import RateLimiter, RateLimitMiddleware, RateLimits
from app.routes import health, receipts


def create_app(
    settings: Settings | None = None,
    rate_limits: RateLimits | None = None,
    clock: Callable[[], float] | None = None,
) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()
    app = FastAPI(
        title="receipt-splitter API",
        version="0.1.0",
        # One ParsedReceipt schema for both request and response bodies (generated TS types).
        separate_input_output_schemas=False,
    )
    # Database dependencies read these settings (see app.db.session), not the global env.
    app.state.settings = settings
    limiter = RateLimiter(clock=clock) if clock else RateLimiter()
    app.state.rate_limiter = limiter

    # Starlette makes the LAST added middleware the OUTERMOST. Request order (outside -> in):
    # CORS -> JSON 500 -> rate limit -> body size -> routes, so every error response carries CORS.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
        limits=rate_limits or RateLimits(),
        hops=settings.rate_limit_trusted_proxy_hops,
        log_client_ip=settings.rate_limit_log_client_ip,
    )
    app.add_middleware(JsonErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_origin_regex=settings.cors_allowed_origin_regex,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
        expose_headers=["Retry-After"],
        allow_credentials=False,
    )
    app.include_router(health.router)
    app.include_router(receipts.router)
    return app


app = create_app()
