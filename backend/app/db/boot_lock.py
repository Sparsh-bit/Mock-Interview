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
_POLL_SECONDS = 0.5


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
    from app.db.session import engine  # noqa: PLC0415 — avoids an import cycle at module load

    deadline = time.monotonic() + wait_seconds
    connection = await engine.connect()
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
