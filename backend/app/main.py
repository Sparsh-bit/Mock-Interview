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

    # ── Request ID middleware ─────────────────────────────────────────────
    @app.middleware("http")
    async def request_id_middleware(request, call_next):
        import uuid

        import structlog

        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
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
