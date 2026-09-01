"""
Alembic environment configuration.

Supports both async (default) and sync migration execution.
All models are imported here so Alembic can auto-generate migrations.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Add backend to sys.path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from app.models import Base  # noqa: E402 — must be after sys.path modification

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# ── WHICH CONNECTION SCHEMA CHANGES USE ──────────────────────────────────────────────────
#
# MIGRATION_DATABASE_URL FIRST, and the reason is an outage rather than tidiness. Alembic's
# correctness rests on a revision applying atomically — its DDL and its `alembic_version`
# update together. That is a transactional guarantee, and a TRANSACTION-MODE pooler cannot
# provide it: each statement may land on a different backend, so DDL can commit while the
# version update never does. The schema ends up AHEAD of the stamp, and the next
# `upgrade head` re-runs a revision whose table already exists:
#
#     asyncpg.exceptions.DuplicateTableError: relation "report_jobs" already exists
#
# boot.py treats that as fatal, the container runs `boot.py && uvicorn`, and the server never
# starts. Deterministic, so it never recovers on its own.
#
# Falls back to DATABASE_URL, so a deployment with no pooler needs no second variable.
database_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
if database_url:
    # Ensure we use the async driver for asyncpg
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without a live connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


#: Is the migration URL going through a TRANSACTION-MODE pooler?
#:
#: MIRRORS app/db/session.py DELIBERATELY, because the two engines point at the same database
#: and must agree about what that database requires. They did not, and the split crashed every
#: deploy:
#:
#:     asyncpg.exceptions.DuplicatePreparedStatementError:
#:       prepared statement "__asyncpg_stmt_1__" already exists
#:     HINT: pgbouncer with pool_mode set to "transaction" ... does not support prepared
#:           statements properly ... set statement_cache_size to 0
#:     [SQL: select pg_catalog.version()]
#:
#: asyncpg prepares every parameterised statement server-side and caches the handle on the
#: connection. Through a transaction-mode pooler a "connection" is a different backend from one
#: transaction to the next, so the handle points at a statement that does not exist there.
#: `select pg_catalog.version()` is SQLAlchemy's own dialect probe on first connect, so this
#: fails before a single migration runs.
#:
#: WHY IT TOOK THE WHOLE SERVICE DOWN. The container runs `boot.py && uvicorn`. A failed
#: migration short-circuits the `&&`, uvicorn never starts, and the platform reports CRASHED or
#: 502 "Application failed to respond" — while the real cause is a prepared-statement complaint
#: several screens up the deploy log, with nothing connecting the two.
_VIA_POOLER = bool(database_url) and (":6543" in database_url or "pgbouncer=true" in database_url)

#: Both names on purpose: `statement_cache_size` reaches asyncpg itself, and
#: `prepared_statement_cache_size` is SQLAlchemy's asyncpg dialect setting. Setting one and not
#: the other leaves half the caching in place.
#:
#: CONDITIONAL, not unconditional. A direct Postgres benefits from the cache and there is no
#: reason to give it up locally — and an unconditional setting would hide whether the detection
#: above works at all.
_CONNECT_ARGS = (
    {"statement_cache_size": 0, "prepared_statement_cache_size": 0} if _VIA_POOLER else {}
)


async def run_async_migrations() -> None:
    """Run migrations in 'online' async mode using asyncpg."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_CONNECT_ARGS,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
