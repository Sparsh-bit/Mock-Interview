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
from dataclasses import dataclass

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


# ─── Connection budget audit ──────────────────────────────────────────────────
#
# THE ARITHMETIC NO SINGLE PROCESS CAN DO. A replica can see its own pool and nothing else,
# but the number the pooler enforces is the whole fleet's:
#
#     (DB_POOL_SIZE + DB_MAX_OVERFLOW) x WEB_REPLICA_COUNT  <=  DB_CONNECTION_CEILING
#
# Past that ceiling Postgres refuses new connections, and the symptom is specifically nasty:
# "too many connections" on scattered random requests rather than a clean slowdown, appearing
# at exactly the traffic that caused it. The engine comment above already explains why the
# pool size matters more than it looks; this is the part that checks it.


@dataclass(frozen=True)
class DbConfigIssue:
    """One thing about the connection budget worth telling an operator at boot."""

    code: str
    message: str
    hint: str


#: Fraction of the ceiling at which the budget is called out before it is breached. Early,
#: because breaching it is not graceful: the pooler starts refusing, and by then the service
#: is already failing requests.
_CEILING_WARN_RATIO = 0.8


def audit_db_connection_budget(
    *,
    pool_size: int,
    max_overflow: int,
    replicas: int,
    ceiling: int,
) -> list[DbConfigIssue]:
    """
    Check the fleet-wide connection budget against the pooler's limit.

    Pure — takes the numbers rather than reading settings — so every threshold can be tested
    at its edge instead of by contriving an environment.

    RETURNS ISSUES TO LOG. NEVER RAISES. An over-subscribed pool still serves every request
    that gets a connection, so this is a degradation that might never be reached; refusing to
    boot would trade it for a certain outage, and would do it during a deploy, when a replica
    is least able to explain itself. Same reasoning main.py already applies to Redis.
    """
    budget = (pool_size + max_overflow) * replicas
    arithmetic = f"({pool_size} + {max_overflow}) x {replicas} replicas = {budget}"

    if ceiling <= 0:
        return [
            DbConfigIssue(
                code="db_connection_ceiling_unknown",
                message=(
                    f"DB_CONNECTION_CEILING is unset, so the connection budget "
                    f"{arithmetic} is not being checked against anything."
                ),
                hint=(
                    "Set it to the pooler's simultaneous client-connection limit "
                    "(Supabase dashboard -> Database -> Connection pooling). See "
                    "docs/DEPLOY.md section 2."
                ),
            )
        ]

    if budget >= ceiling:
        return [
            DbConfigIssue(
                code="db_connection_budget_over_ceiling",
                message=(
                    f"Database connection budget {arithmetic}, at or over the pooler "
                    f"ceiling of {ceiling}."
                ),
                hint=(
                    "Lower DB_POOL_SIZE / DB_MAX_OVERFLOW before lowering WEB_REPLICA_COUNT "
                    "— behind a transaction pooler the app should hold FEW server "
                    "connections and let the pooler multiplex. Past the ceiling Postgres "
                    "refuses new connections and the symptom is 'too many connections' on "
                    "random requests, not a clean slowdown."
                ),
            )
        ]

    if budget >= ceiling * _CEILING_WARN_RATIO:
        return [
            DbConfigIssue(
                code="db_connection_budget_near_ceiling",
                message=(
                    f"Database connection budget {arithmetic}, within "
                    f"{int((1 - _CEILING_WARN_RATIO) * 100)}% of the pooler ceiling of "
                    f"{ceiling}."
                ),
                hint=(
                    "One more replica breaches it. Anything else sharing the pooler — a "
                    "migration, a psql session, a second service — eats the same headroom."
                ),
            )
        ]

    return []


def log_db_connection_budget_audit() -> list[DbConfigIssue]:
    """Run the audit against live settings and log each issue. Called from the lifespan."""
    issues = audit_db_connection_budget(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        replicas=settings.PROCESS_COUNT,
        ceiling=settings.DB_CONNECTION_CEILING,
    )
    for issue in issues:
        logger.warning(issue.code, message=issue.message, hint=issue.hint)
    return issues


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
