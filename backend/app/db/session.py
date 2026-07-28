"""
Database Session — db/session.py

Async SQLAlchemy engine, session factory, and FastAPI dependency.
Uses asyncpg driver for PostgreSQL.

All database I/O in this application uses async sessions.
Never import a synchronous session; never call session.execute() outside of an async context.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import orjson
import structlog
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = structlog.get_logger(__name__)


def _orjson_dumps(value: object) -> str:
    """orjson.dumps returns bytes; SQLAlchemy's json_serializer must return str."""
    return orjson.dumps(value).decode("utf-8")


# ─── Engine ───────────────────────────────────────────────────────────────────

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,
    json_serializer=_orjson_dumps,
    json_deserializer=orjson.loads,
)

# Session factory — use this everywhere via the get_db() dependency
AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Objects remain accessible after commit
    autocommit=False,
    autoflush=False,
)

# ─── FastAPI dependency ───────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async database session.

    The session is committed automatically on success and rolled back on error.
    If the caller already committed the session manually, rollback is safely skipped.
    A new session is created per request and closed when the request completes.

    Usage:
        @router.post("/interview/start")
        async def start_interview(
            db: AsyncSession = Depends(get_db),
        ):
            ...
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            with contextlib.suppress(Exception):
                await session.rollback()
            raise
        finally:
            await session.close()


# ─── Context manager for non-FastAPI use (event handlers, scripts) ────────────


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions outside of FastAPI request scope.

    Usage:
        async with get_db_session() as db:
            result = await db.execute(select(User))

    Used by:
        - Event handlers (persist_event_handler)
        - Background tasks
        - CLI scripts
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ─── Health check ─────────────────────────────────────────────────────────────


async def check_db_connection() -> bool:
    """
    Verify the database is reachable.
    Used by GET /api/v1/health.
    Never raises — returns False on failure.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("db_health_check_failed")
        return False


# Re-export for type hints in other modules
__all__ = ["AsyncSession", "get_db", "get_db_session", "check_db_connection", "engine"]


async def check_schema_drift() -> dict[str, list[str]]:
    """
    Report columns the ORM models declare that the database does not have.

    Exists because this class of bug is silent and expensive: production's
    `reports` table was missing `readiness_level`, so every read of that table
    raised UndefinedColumnError. Because FastAPI's bare-Exception handler sits
    outside CORSMiddleware, the 500 reached the browser as a CORS error with no
    status and no message — the interview report was unfetchable for days and the
    console pointed at the wrong subsystem entirely.

    Drift arises when a database is created outside Alembic (a hand-made schema,
    or `alembic stamp` without a run), so migrations that would have added the
    columns are recorded as already applied.

    Never raises: this is diagnostics, and it must not be able to stop startup.
    Returns {table: [missing columns]}, empty when the schema matches.
    """
    from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415

    from app.models.base import Base  # noqa: PLC0415

    drift: dict[str, list[str]] = {}
    try:
        async with engine.connect() as conn:
            def _collect(sync_conn) -> dict[str, list[str]]:
                inspector = sa_inspect(sync_conn)
                present = set(inspector.get_table_names())
                found: dict[str, list[str]] = {}
                for table in Base.metadata.sorted_tables:
                    if table.name not in present:
                        found[table.name] = ["<table missing>"]
                        continue
                    actual = {c["name"] for c in inspector.get_columns(table.name)}
                    missing = [c.name for c in table.columns if c.name not in actual]
                    if missing:
                        found[table.name] = missing
                return found

            drift = await conn.run_sync(_collect)
    except Exception:  # noqa: BLE001 — diagnostics must never break startup
        logger.warning("schema_drift_check_failed")
        return {}

    return drift
