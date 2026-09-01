"""
Container boot — scripts/boot.py

Migrations and reference-data seeding, run under a Postgres advisory lock so that N replicas
booting the same deploy do it once between them instead of N times at once.

WHAT THIS REPLACED. The Dockerfile CMD used to be

    alembic upgrade head && (seed_db.py) && (seed_research.py) && uvicorn

with every replica running the whole chain. At one instance that is correct. At two, a deploy
carrying a migration has both replicas applying the same DDL: Postgres holds the second behind
the first's ACCESS EXCLUSIVE lock, the first commits, and the second's `CREATE TABLE` fails
with "relation already exists". `alembic` exits non-zero, the `&&` short-circuits, and that
replica never starts Uvicorn — so the deploy comes up at half capacity and the cause is a line
of Postgres error text in a log nobody is reading. The seeds are the same race one level down:
SELECT-then-INSERT with nothing serialising them.

THIS IS THE SECOND LINE OF DEFENCE, NOT THE FIRST. render.yaml's `preDeployCommand` runs the
migration once per deploy, before any new instance starts, which is the platform's own answer
and the better one. This exists because the container must be correct without it: on a plan
with no pre-deploy hook, under docker-compose, and for whoever eventually edits the CMD back
without knowing why it changed.

Exit codes are load-bearing — the CMD chains on `&&`:
  0  boot work done, or deliberately skipped because another replica is doing it
  1  the work was ours and it failed; Uvicorn must not start on an unmigrated schema
"""

from __future__ import annotations

import asyncio
import os
import subprocess  # noqa: S404 — running our own migration tooling, no shell, fixed argv
import sys

import structlog

from app.db.boot_lock import _DEFAULT_LOCK_WAIT_SECONDS, boot_lock

logger = structlog.get_logger(__name__)

#: How long a replica waits for whichever one is migrating.
#:
#: THE DEFAULT NOW COMES FROM boot_lock, and the old comment here is why it had to move. It
#: read "the platform's own health-check grace period is what bounds it in practice" — which
#: was the mistake. The platform does not bound a wait, it KILLS the container: 300 seconds
#: inside a 120-second boot window could only ever end that way, quietly, because the poll
#: loop logs nothing until it gives up.
#:
#: Kept overridable for a platform with a genuinely larger window. See
#: boot_lock._DEFAULT_LOCK_WAIT_SECONDS for the arithmetic.
_LOCK_WAIT_SECONDS = float(
    os.environ.get("BOOT_LOCK_WAIT_SECONDS", str(_DEFAULT_LOCK_WAIT_SECONDS))
)

#: Ordered. Migrations first — the seeds write rows into tables the migrations create.
#:
#: The seeds are non-fatal and the migration is not, which is the same split the old CMD had:
#: reference data failing to refresh must never stop the API from starting, whereas serving
#: requests against a schema the code does not match produces 500s that reach the browser as
#: CORS errors and are near-invisible.
_STEPS: list[tuple[str, list[str], bool]] = [
    ("migrations", ["uv", "run", "alembic", "upgrade", "head"], True),
    ("catalogue_seed", ["uv", "run", "python", "scripts/seed_db.py"], False),
    ("research_seed", ["uv", "run", "python", "scripts/seed_research.py"], False),
]


#: The signature of a schema that is AHEAD of `alembic_version`.
#:
#: WHY THIS IS WORTH RECOGNISING BY HAND. The raw failure is
#: `DuplicateTableError: relation "report_jobs" already exists`, which names a table and
#: nothing else — not that the version stamp is behind, not that the container is about to
#: exit, not what to do. Downstream the symptom is 502 on every path and a browser console
#: full of CORS errors, because a 502 page carries no Access-Control-Allow-Origin. Nothing in
#: that chain points back here, and the condition is deterministic, so it never self-heals.
#: Naming it turns hours of bisecting into one command.
_SCHEMA_AHEAD_MARKERS = ("already exists", "DuplicateTable", "DuplicateColumn", "DuplicateObject")


def _diagnose_schema_ahead(output: str) -> None:
    """Explain a migration that failed because the object it creates is already there."""
    if not any(marker in output for marker in _SCHEMA_AHEAD_MARKERS):
        return
    logger.error(
        "migration_failed_schema_ahead_of_alembic_version",
        why=(
            "A revision tried to create something that already exists, which means the "
            "database schema is AHEAD of the revision recorded in alembic_version. Alembic "
            "will retry the same revision on every boot, so this never clears by itself."
        ),
        how_it_happens=(
            "Most often migrations were run through a TRANSACTION-MODE pooler (Supabase port "
            "6543), where a revision's DDL can commit while its alembic_version update does "
            "not — the two are only atomic on a session-mode connection. Set "
            "MIGRATION_DATABASE_URL to the session pooler (port 5432) so this cannot recur."
        ),
        repair=(
            "Find the true state, then stamp it: `SELECT version_num FROM alembic_version;` "
            "and compare against database/migrations/versions/. Stamp the highest revision "
            "whose objects all exist — `alembic stamp <rev>` — then `alembic upgrade head`. "
            "Stamping does not touch data; it only corrects the bookmark."
        ),
    )


def _run(name: str, argv: list[str], fatal: bool) -> bool:
    """Run one step. Returns False only when a fatal step failed."""
    logger.info("boot_step_started", step=name)
    # CAPTURED SO IT CAN BE READ, THEN RE-EMITTED SO NOTHING IS LOST. The traceback is how the
    # next unknown failure gets diagnosed; swallowing it to inspect it would trade one blind
    # spot for another.
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        argv, check=False, capture_output=True, text=True
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode == 0:
        logger.info("boot_step_finished", step=name)
        return True
    if fatal:
        logger.error("boot_step_failed", step=name, exit_code=result.returncode)
        _diagnose_schema_ahead(f"{result.stdout}{result.stderr}")
        return False
    logger.warning("boot_step_skipped", step=name, exit_code=result.returncode)
    return True


async def main() -> int:
    async with boot_lock(wait_seconds=_LOCK_WAIT_SECONDS) as acquired:
        if not acquired:
            # Another replica holds it, which means another replica is doing this work.
            # Starting anyway is the right call: the alternative is a replica that refuses
            # to boot while the fleet is mid-deploy. main.py's check_schema_drift reports
            # loudly if this turns out to have been wrong.
            logger.warning(
                "boot_work_skipped_another_replica_holds_the_lock",
                hint="check the other replica's logs for boot_step_failed",
            )
            return 0

        for name, argv, fatal in _STEPS:
            if not _run(name, argv, fatal):
                return 1

    logger.info("boot_work_complete")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
