"""
Boot serialisation — db/boot_lock.py

THE PROBLEM THIS EXISTS FOR. The container's CMD is

    alembic upgrade head && (seed_db.py) && (seed_research.py) && uvicorn

and EVERY replica runs it. With one instance that is fine and has been fine. With two, a
deploy that carries a migration has both replicas applying the same DDL at the same time:
Postgres holds the second behind an ACCESS EXCLUSIVE lock, the first commits, and the
second's `CREATE TABLE` fails with "relation already exists". `alembic` exits non-zero, the
`&&` short-circuits, and that replica never starts Uvicorn at all. The seeds have the same
shape one level down — SELECT-then-INSERT with nothing serialising them.

WHY AN ADVISORY LOCK AND NOT SOMETHING BIGGER. A Postgres advisory lock is a native
primitive over the database both replicas already share; there is no new service, no new
state and nothing to keep alive. It is the standard answer to "exactly one of these
processes should do this", and the alternative — a leader election, or a queue — would be
inventing machinery for a problem the database already solves.

The platform-level fix sits alongside it rather than instead of it: `preDeployCommand` in
render.yaml runs the migration once per deploy, before any new instance starts. This lock is
what keeps the container correct anyway — on a plan with no pre-deploy hook, under
docker-compose, and for anybody who reverts the CMD without knowing why it changed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)

#: The advisory lock two replicas must agree on. A literal, not a hash of anything about
#: the environment: derive it from the database name, the release, or the hostname and each
#: replica quietly gets its own lock, which is indistinguishable from having none.
#:
#: Advisory lock keys share one namespace across the whole database, so this is deliberately
#: an unusual number rather than a small one — a collision with another application's lock
#: would serialise two unrelated things and look like a hang.
BOOT_LOCK_KEY = 0x484F5453454154  # "HOTSEAT" in ASCII, as an integer

#: How often a waiting replica retries. Short enough that it starts promptly once the
#: migration finishes, long enough not to spin.
#: How long to wait for the lock before booting without it.
#:
#: THE OLD DEFAULT WAS 300 SECONDS, WHICH COULD ONLY EVER END AS A KILL. The reasoning behind
#: it was sound in isolation — "the cost of waiting is a slower boot; the cost of giving up
#: early is booting against a half-applied schema" — but it ignored the ceiling: the platform
#: gives the whole boot 120 seconds (healthcheckTimeout in railway.json). A five-minute wait
#: inside a two-minute window is not patience, it is an outage, and a quiet one: the poll loop
#: logs nothing until it gives up, so the deploy log ends mid-startup with no explanation.
#:
#: 60 seconds is longer than any migration in database/migrations/ takes and leaves the rest of
#: the window for the migration itself, the seeds and the lifespan. Past it, the caller boots
#: anyway and says so — main.py's schema-drift check reports if that turns out to have been
#: the wrong call.
#:
#: Overridable with BOOT_LOCK_WAIT_SECONDS for a deployment whose platform window is genuinely
#: larger. Raising it past the window buys nothing.
_DEFAULT_LOCK_WAIT_SECONDS = 60.0

_POLL_SECONDS = 0.5


def lock_is_meaningless(database_url: str) -> bool:
    """
    True when a SESSION-scoped advisory lock cannot be honoured by the far end.

    Supabase's TRANSACTION pooler (port 6543, or any URL carrying `pgbouncer=true`) assigns a
    server backend per TRANSACTION. `pg_try_advisory_lock` taken through it can land on one
    backend while the migration runs on another and the unlock on a third, so the lock protects
    nothing — and the code that believes it does can loop or raise, which is fatal here because
    the container runs `boot.py && uvicorn`: no boot, no server, and the platform answers 502
    with no application error to read.

    THE SESSION POOLER (port 5432 on the same host) IS FINE and must not be caught: a client
    keeps one backend for the life of the connection there, which is exactly the guarantee a
    session-scoped lock needs. Only the transaction port is a problem, which is why this tests
    the port rather than the hostname.
    """
    return ":6543" in database_url or "pgbouncer=true" in database_url


@asynccontextmanager
async def boot_lock(*, wait_seconds: float) -> AsyncIterator[bool]:
    """
    Hold the boot advisory lock for the body, or yield False if it could not be taken.

    Yields True when this process holds the lock and should do the boot work, False when
    the wait expired — meaning another replica is doing it, and this one should NOT push on
    and race. Handing back False rather than raising is deliberate: the caller decides what
    to do about it, and the two callers want different things.

    `pg_try_advisory_lock` in a poll loop rather than the blocking `pg_advisory_lock`,
    because the blocking form has no timeout that does not also apply to real queries
    (`lock_timeout` is per-statement and would have to be set and unset around it), and a
    boot that waits forever on a lock some crashed replica never released is worse than one
    that reports it could not get it.

    The lock is SESSION-scoped and taken on a dedicated connection, so it survives the
    subprocesses the caller runs under it and is released by the `finally` — or, if the
    process dies outright, by Postgres when the connection drops. There is no path that
    leaves it held.
    """
    from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

    from app.core.config import settings  # noqa: PLC0415

    # ── THE LOCK IS UNAVAILABLE BEHIND A TRANSACTION POOLER ──────────────────────────────
    #
    # Skipped rather than attempted, and said out loud. See lock_is_meaningless: through
    # transaction pooling this lock cannot be honoured, and pretending otherwise risks the
    # boot hanging on a connection — which takes uvicorn with it, because CMD is
    # `boot.py && uvicorn`.
    #
    # YIELDS TRUE, so the boot work still happens. At one replica nothing is lost: there is no
    # second booter to race. At several, concurrent migrations become possible again — which is
    # precisely what this lock was written to prevent — so the warning names the fix.
    # THE MIGRATION URL, not the app's. When a session-mode MIGRATION_DATABASE_URL is
    # configured the lock is honoured again and this branch does not trigger — which is the
    # point: give schema work a connection whose sessions are real and both problems go away
    # together.
    if lock_is_meaningless(settings.migration_database_url):
        logger.warning(
            "boot_lock_skipped_behind_transaction_pooler",
            hint=(
                "A session-scoped advisory lock cannot be honoured through transaction "
                "pooling, so it is not attempted. Safe at one replica. For several, point "
                "boot at a DIRECT (non-pooled) database URL so the lock works again."
            ),
        )
        yield True
        return

    # ── ITS OWN CONNECTION, FROM THE URL THE DECISION WAS MADE ABOUT ─────────────────────
    #
    # THIS BORROWED THE APPLICATION'S ENGINE AND THAT CAUSED A CRASH LOOP. The check above
    # reads `migration_database_url`, correctly — the lock guards schema work. The connection
    # was opened from app.db.session.engine, which is built from DATABASE_URL. Those are the
    # SAME url until MIGRATION_DATABASE_URL is set, and different the moment it is: the check
    # then said "the lock is honoured here" (session pooler, 5432) while the lock was actually
    # taken through the transaction pooler (6543), where a session-scoped lock cannot stick.
    #
    # pg_try_advisory_lock then keeps returning false, this poll loop runs to `wait_seconds`,
    # and the platform kills the container at its own boot window first — quietly, because the
    # loop logs nothing until it gives up.
    #
    # NullPool because this is one connection used once. Its own engine, disposed in the
    # `finally`, so it cannot disturb the application's pool — which at four workers is
    # already sized against a pooler with a fixed number of backends.
    from sqlalchemy.pool import NullPool  # noqa: PLC0415

    lock_engine = create_async_engine(
        settings.migration_database_url,
        poolclass=NullPool,
        connect_args=(
            {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
            if lock_is_meaningless(settings.migration_database_url)
            else {}
        ),
    )

    deadline = time.monotonic() + wait_seconds
    connection = await lock_engine.connect()
    acquired = False
    try:
        while True:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": BOOT_LOCK_KEY}
                )
            )
            if acquired or time.monotonic() >= deadline:
                break
            await asyncio.sleep(_POLL_SECONDS)

        if not acquired:
            logger.warning(
                "boot_lock_not_acquired",
                waited_seconds=round(wait_seconds, 1),
                hint=(
                    "another replica is holding it. Migrations and seeds are being skipped "
                    "here rather than raced; check that replica's logs."
                ),
            )
        yield acquired
    finally:
        if acquired:
            # Best effort: if the connection is already gone, Postgres has released the
            # lock for us and the unlock is redundant rather than missed.
            try:
                await connection.exec_driver_sql(
                    f"SELECT pg_advisory_unlock({BOOT_LOCK_KEY})"
                )
            except Exception:  # noqa: BLE001 — never let unlock failure mask the real error
                logger.warning("boot_lock_unlock_failed", exc_info=True)
        await connection.close()
        # Its own engine, so its own disposal. Leaving it would hold a pooler client
        # connection open for the life of the process for nothing.
        await lock_engine.dispose()
