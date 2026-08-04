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
from fastapi.responses import ORJSONResponse

from app.api.v1.reports import mark_request_served
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging

# Configure logging before anything else
configure_logging(
    log_level=settings.LOG_LEVEL,
    log_format=settings.LOG_FORMAT,
)

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

    # Verify Redis connection
    from app.db.redis import check_redis_connection
    redis_ok = await check_redis_connection()
    if not redis_ok:
        logger.warning("redis_unreachable_at_startup")
    else:
        logger.info("redis_connected")

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
        default_response_class=ORJSONResponse,
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
