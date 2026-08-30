"""
FastAPI Application Entry Point — app/main.py

Wires together all application layers:
  - Structured logging
  - CORS middleware
  - API versioned router
  - Exception handlers
  - Lifespan (startup / shutdown hooks)
  - Event bus initialization
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.reports import mark_request_served
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.observability import init_sentry

# Configure logging before anything else
configure_logging(
    log_level=settings.LOG_LEVEL,
    log_format=settings.LOG_FORMAT,
)

# Then error tracking, at import time rather than in the lifespan hook: an exception
# raised while the app object is being constructed — a bad setting, a router that
# fails to import — happens before any lifespan runs, and that is exactly the class
# of failure worth a report. No-op when SENTRY_DSN is unset.
init_sentry()

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan — runs startup hooks before yield, shutdown hooks after.
    """
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("application_startup", env=settings.ENVIRONMENT, version=settings.APP_VERSION)

    # Initialize event bus (attaches default handlers)
    from app.events.event_bus import initialize_event_bus
    initialize_event_bus()
    logger.info("event_bus_ready")

    # Verify DB connection
    from app.db.session import check_db_connection
    db_ok = await check_db_connection()
    if not db_ok:
        logger.error("database_unreachable_at_startup")
        if settings.is_production:
            raise RuntimeError("Database is unreachable. Aborting startup.")
    else:
        logger.info("database_connected")

        # Surface schema drift loudly. A missing column only shows up as a 500 on
        # whichever endpoint touches it, and those 500s reach the browser as CORS
        # errors — so without this it is near-invisible. Logged, never fatal.
        from app.db.session import check_schema_drift  # noqa: PLC0415

        drift = await check_schema_drift()
        if drift:
            logger.error(
                "schema_drift_detected",
                tables=drift,
                hint="run `alembic upgrade head`; endpoints touching these tables will 500",
            )
        else:
            logger.info("schema_matches_models")

    # Verify Redis connection.
    #
    # NOT a hard failure — unlike the database, every Redis-backed feature degrades
    # rather than breaking, so refusing to boot would trade a working-but-degraded
    # service for no service at all.
    #
    # But it is an ERROR in production, not a warning, because THREE things silently
    # stop protecting the service and none of them announces itself at the point of
    # failure:
    #
    #   * rate limiting fails OPEN (core/rate_limit.py catches RedisError and returns),
    #     so every limit in the app stops existing — including the 6/hour on report
    #     generation, the most expensive call there is
    #   * the AI daily spend cap falls back to a per-PROCESS counter
    #     (anthropic_provider._spend_today returns `local`), so the effective ceiling
    #     becomes AI_DAILY_BUDGET_USD x instance count, and resets to zero on restart
    #   * the interview-plan semantic cache always misses (semantic_cache returns []),
    #     so every plan is bought again at ~$0.065
    #
    # The first two are the ones that cost money, which is why this is loud.
    from app.db.redis import check_redis_connection, log_redis_configuration_audit

    # Configuration first, reachability second. The things this reports — plaintext in
    # production, a connection budget over the provider's ceiling — are invisible to a
    # process that can only see its own pool, and they are exactly the failures that a
    # successful PING does not rule out.
    log_redis_configuration_audit()

    redis_ok = await check_redis_connection()
    if redis_ok:
        logger.info("redis_connected")
    elif settings.is_production:
        logger.error(
            "redis_unreachable_at_startup_running_degraded",
            hint=(
                "rate limiting is disabled, the AI spend cap is per-process and resets "
                "on restart, and the interview-plan cache always misses. Set REDIS_URL."
            ),
        )
    else:
        logger.warning("redis_unreachable_at_startup")

    # Warm prompt template cache
    from app.prompts.prompt_loader import get_prompt_loader
    loader = get_prompt_loader()
    logger.info("prompts_loaded", available=loader.list_prompts())

    # Initialize the AI provider (application-scoped singleton, owns the
    # underlying httpx.AsyncClient connection pool)
    from app.services.ai.provider_factory import initialize_ai_provider
    ai_provider = initialize_ai_provider()
    logger.info("ai_provider_ready", provider=ai_provider.provider_name, model=ai_provider.model_name)

    logger.info("application_ready")

    yield  # Application running

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("application_shutdown")

    from app.services.ai.provider_factory import close_ai_provider
    await close_ai_provider()

    from app.db.redis import close_redis_pool
    await close_redis_pool()

    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""

    app = FastAPI(
        title=settings.APP_NAME,
        description="AI-powered mock interview platform API",
        version=settings.APP_VERSION,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        # NO `default_response_class=ORJSONResponse`, and it is not an oversight. FastAPI now
        # serialises to JSON bytes directly whenever a route declares a return type or a
        # response_model — which every route here does — and its own deprecation notice says
        # that path is faster than routing through a custom response class. Keeping it emitted
        # a FastAPIDeprecationWarning per route, eleven of the seventeen warnings in a full
        # test run, which is how a real warning ends up invisible among the noise.
        #
        # Error responses still construct ORJSONResponse explicitly in core/exceptions.py, and
        # that is unaffected: this setting was only ever the DEFAULT for routes that named
        # none.
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    cors_origins = list(settings.CORS_ORIGINS)
    if settings.is_development:
        cors_origins.extend([
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:3002",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://127.0.0.1:3002",
        ])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):.*" if settings.is_development else None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # ── Security headers ──────────────────────────────────────────────────
    #
    # This service returns JSON, so the browser-facing risks are narrower than for
    # a page — but a JSON endpoint can still be framed, sniffed into a different
    # content type, or leak its URLs through the Referer header on any redirect.
    # These are cheap, have no downside for an API, and are the difference between
    # "we never thought about it" and a deliberate posture.
    #
    # No Content-Security-Policy here on purpose: the API serves no HTML, and a CSP
    # belongs on the frontend origin (Cloudflare), where the scripts actually load.
    @app.middleware("http")
    async def security_headers_middleware(request, call_next):
        response = await call_next(request)

        # Never let a browser second-guess our declared content type. This is what
        # stops a JSON response containing attacker-supplied text from being
        # sniffed and executed as HTML or JavaScript.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # An API has no legitimate reason to be embedded in a frame.
        response.headers.setdefault("X-Frame-Options", "DENY")
        # Send no Referer to other origins: request paths here contain session and
        # report UUIDs, which should not travel to third parties.
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        # Nothing here needs a camera, microphone or location. Deny by default so
        # the answer does not depend on a future handler remembering to.
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )

        # HSTS only in production, and only over TLS. Sending it in development
        # would pin localhost to https and break the dev server in a way that is
        # painful to undo — browsers cache it aggressively.
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

        return response

    # ── Request ID middleware ─────────────────────────────────────────────
    @app.middleware("http")
    async def request_id_middleware(request, call_next):
        import uuid

        import structlog

        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        # This process has now served a request, so nothing after this point can be the
        # one that paid the container cold start. Report generation reads this to choose
        # its time budget — see _REPORT_AI_BUDGET_COLD_SECONDS in api/v1/reports.py.
        # Set here rather than in the endpoint so the signal is true even when the first
        # request served is something else entirely.
        mark_request_served()
        structlog.contextvars.unbind_contextvars("request_id")
        return response

    # ── Exception handlers ────────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ───────────────────────────────────────────────────────────
    from app.api.v1.router import v1_router
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

    return app


# Application instance
app = create_app()
