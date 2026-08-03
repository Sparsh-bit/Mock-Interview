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

#: Is this connection going through a transaction-mode connection pooler?
#:
#: Supabase's pooler listens on 6543 (the direct Postgres port is 5432). Detected
#: from the URL rather than configured separately, because two settings that must
#: agree are two settings that will eventually disagree — and the failure when they
#: do is a prepared-statement error under load, which is the worst time to find out.
_VIA_POOLER = ":6543" in settings.DATABASE_URL or "pgbouncer=true" in settings.DATABASE_URL

#: asyncpg prepares every statement server-side and caches the handle on the
#: connection. In a transaction-mode pooler a "connection" is a different backend
#: from one transaction to the next, so a cached handle points at a prepared
#: statement that does not exist there — asyncpg raises
#: InvalidSQLStatementNameError, and it only happens once there is enough
#: concurrency for connections to actually be multiplexed. That is precisely the
#: load at which nobody wants to be debugging it.
_asyncpg_args: dict[str, object] = (
    {"statement_cache_size": 0, "prepared_statement_cache_size": 0} if _VIA_POOLER else {}
)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    # WHY THE POOL SIZE MATTERS MORE THAN IT LOOKS. Every replica opens its own
    # pool, so the ceiling is pool_size + max_overflow TIMES the replica count, and
    # Postgres refuses connections past its own limit — which surfaces as
    # "too many connections" on random requests rather than as a clean degradation.
    # Behind a pooler the app should hold FEW server connections and let the pooler
    # do the multiplexing; direct to Postgres it needs enough to serve its own
    # concurrency. Both come from settings so a Railway replica count change is a
    # config change, not a deploy.
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    # Recycle before any pooler or network idle timeout can close a connection under
    # us. Without it the first request after a quiet period fails with a closed
    # connection — rare in testing, constant in production at low traffic.
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    json_serializer=_orjson_dumps,
    json_deserializer=orjson.loads,
    connect_args=_asyncpg_args,
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
                    db_cols = {c["name"]: c for c in inspector.get_columns(table.name)}
                    model_cols = {c.name for c in table.columns}

                    problems = [
                        f"model-only:{c.name}"
                        for c in table.columns
                        if c.name not in db_cols
                    ]
                    # The reverse direction breaks WRITES rather than reads, so it
                    # is easy to miss: a leftover NOT NULL column with no default
                    # that the model never populates makes every INSERT fail while
                    # every SELECT keeps working. Columns that are nullable or
                    # defaulted are harmless, so only flag the ones that block
                    # inserts.
                    problems += [
                        f"db-only-required:{name}"
                        for name, col in db_cols.items()
                        if name not in model_cols
                        and not col.get("nullable", True)
                        and col.get("default") is None
                        and not col.get("autoincrement", False)
                    ]
                    if problems:
                        found[table.name] = problems
                return found

            drift = await conn.run_sync(_collect)
    except Exception:  # noqa: BLE001 — diagnostics must never break startup
        logger.warning("schema_drift_check_failed")
        return {}

    return drift
