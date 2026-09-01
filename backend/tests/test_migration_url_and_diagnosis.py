"""
Migrations get a session-mode connection, and a failed boot explains itself.

THE OUTAGE THIS COMES FROM, reproduced end to end in a container before being fixed.

    alembic_version = "023", while the tables created by revisions 024, 025 and 026 all
    exist. `alembic upgrade head` therefore re-runs 024, whose op.create_table has no
    existence guard, and dies:

        asyncpg.exceptions.DuplicateTableError: relation "report_jobs" already exists

    boot.py's migration step is fatal, so it returns 1. The container's CMD is
    `boot.py && uvicorn`, so the `&&` short-circuits and uvicorn never starts. The
    platform answers 502 on every path, the browser reports every request as a CORS
    failure because a 502 page carries no Access-Control-Allow-Origin, and because the
    condition is deterministic it NEVER self-heals. A permanent, self-perpetuating outage.

    Proof it was only the data: the same image against a CLEAN database booted in nine
    seconds with all four workers reaching application_ready.

HOW THE SCHEMA AND THE VERSION STAMP CAME APART, which is the actual root cause. Alembic's
correctness rests on one guarantee: a revision either fully applies — DDL *and* the
alembic_version update — or not at all. That guarantee is transactional, and a
TRANSACTION-MODE POOLER cannot provide it: each statement may be handed a different backend,
so DDL can commit while the version update lands somewhere that never commits. Migrations run
over port 6543 are therefore not safe, and Supabase's own guidance is to use a direct or
session connection for them.

So MIGRATION_DATABASE_URL exists: the app keeps the transaction pooler, which is what makes
high concurrency possible, and schema changes get a connection whose transactions mean
something. It also restores boot_lock's session-scoped advisory lock for free.

THE SECOND FIX IS ABOUT THE HOURS THIS COST. A DuplicateTableError names a table and nothing
else — not that the version stamp is behind, not what to do about it. boot.py now recognises
the signature and prints the diagnosis and the repair.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PY = (REPO_ROOT / "database/migrations/env.py").read_text()
BOOT_PY = (REPO_ROOT / "backend/scripts/boot.py").read_text()


class TestMigrationsGetTheirOwnUrl:
    def test_the_setting_exists_and_falls_back(self):
        s = Settings.model_construct(
            DATABASE_URL="postgresql+asyncpg://u:p@h:6543/db", MIGRATION_DATABASE_URL=""
        )
        # Unset means "same as the app", which keeps single-database deployments working.
        assert s.migration_database_url == "postgresql+asyncpg://u:p@h:6543/db"

    def test_an_explicit_migration_url_wins(self):
        s = Settings.model_construct(
            DATABASE_URL="postgresql+asyncpg://u:p@h:6543/db",
            MIGRATION_DATABASE_URL="postgresql+asyncpg://u:p@h:5432/db",
        )
        assert ":5432" in s.migration_database_url

    def test_the_driver_is_normalised_like_the_app_url(self):
        s = Settings.model_construct(
            DATABASE_URL="postgresql+asyncpg://u:p@h:6543/db",
            MIGRATION_DATABASE_URL="postgresql://u:p@h:5432/db",
        )
        assert s.migration_database_url.startswith("postgresql+asyncpg://")

    def test_alembic_prefers_it(self):
        assert "MIGRATION_DATABASE_URL" in ENV_PY, (
            "env.py still reads only DATABASE_URL, so migrations run through whatever the app "
            "uses — including a transaction pooler, where a revision's DDL can commit without "
            "its version stamp."
        )
        # And it must be preferred over DATABASE_URL, not merely mentioned.
        assert ENV_PY.index("MIGRATION_DATABASE_URL") < ENV_PY.index('os.environ.get("DATABASE_URL")')

    def test_the_boot_lock_uses_it_too(self):
        lock = (REPO_ROOT / "backend/app/db/boot_lock.py").read_text()
        assert "migration_database_url" in lock, (
            "the advisory lock is session-scoped, so it needs the same session-mode connection "
            "the migrations use — otherwise it is still skipped for nothing."
        )


class TestAFailedMigrationExplainsItself:
    def test_boot_recognises_the_desync_signature(self):
        assert "already exists" in BOOT_PY, (
            "a DuplicateTableError names a table and nothing else. boot.py should recognise it "
            "and say that the schema is ahead of alembic_version."
        )

    def test_it_names_the_repair(self):
        # An error that does not say what to do is a puzzle, not a diagnosis.
        assert "alembic stamp" in BOOT_PY
        assert "alembic_version" in BOOT_PY

    def test_it_still_re_emits_the_original_output(self):
        """
        Capturing the subprocess to inspect it must not swallow it: the traceback is how the
        NEXT unknown failure gets diagnosed.
        """
        assert "capture_output" in BOOT_PY or "stdout=" in BOOT_PY
        assert "sys.stderr" in BOOT_PY or "print(" in BOOT_PY

    def test_the_migration_step_is_still_fatal(self):
        """
        THE VACUITY GUARD. Diagnosing it must not become "continue anyway" — serving requests
        against a schema the code does not match produces 500s that reach the browser as CORS
        errors, which is the failure this whole file is about, one layer up.
        """
        step = BOOT_PY[BOOT_PY.index('("migrations"') : BOOT_PY.index('("migrations"') + 200]
        assert "True" in step
