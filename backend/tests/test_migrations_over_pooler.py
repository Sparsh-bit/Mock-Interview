"""
Alembic gets the same pooler treatment as the app — tests/test_migrations_over_pooler.py

THE SPLIT THAT CAUSED A CRASH LOOP. `app/db/session.py` detects a transaction-mode pooler
(`:6543`, or `pgbouncer=true`) and disables asyncpg's prepared-statement cache, and its own
comment explains why in detail: asyncpg prepares every parameterised statement server-side and
caches the handle on the connection, but in transaction mode a "connection" is a different
backend from one transaction to the next, so the cached handle points at a statement that does
not exist there and asyncpg raises InvalidSQLStatementNameError.

`database/migrations/env.py` builds its OWN engine with `async_engine_from_config(...)` and had
none of that. So the application was pooler-safe and its migrations were not.

WHY THAT IS FATAL RATHER THAN ANNOYING. The container's CMD is
`boot.py && uvicorn`, so a failed migration short-circuits the `&&` and uvicorn never starts.
The platform reports CRASHED or 502 "Application failed to respond", and the actual error is a
prepared-statement complaint several screens up the deploy log — nothing about the symptom
points at Alembic.

This is a source-level assertion because exercising it needs a live transaction pooler. The
value is in the coupling: two engines pointed at the same database must agree about the driver
settings that database requires.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PY = (REPO_ROOT / "database/migrations/env.py").read_text()
SESSION_PY = (REPO_ROOT / "backend/app/db/session.py").read_text()


class TestBothEnginesAgreeAboutThePooler:
    def test_the_app_engine_disables_the_statement_cache(self):
        # Guards the guard: if this ever stops being true, the assertion below is comparing
        # against nothing.
        assert "statement_cache_size" in SESSION_PY
        assert "6543" in SESSION_PY

    def test_alembic_detects_the_transaction_pooler_too(self):
        assert "6543" in ENV_PY, (
            "env.py does not detect a transaction-mode pooler, so migrations run with "
            "asyncpg's prepared-statement cache on — which fails on Supabase's port 6543 and "
            "takes the whole boot down with it, because CMD is `boot.py && uvicorn`."
        )
        assert "pgbouncer" in ENV_PY

    def test_alembic_passes_connect_args_to_its_engine(self):
        """
        The setting has to reach the engine, not merely be computed. A helper nothing wires in
        protects nothing — the same failure docs/MISTAKES.md records for NudgeDeck.
        """
        assert "connect_args" in ENV_PY
        assert "statement_cache_size" in ENV_PY
        assert "prepared_statement_cache_size" in ENV_PY

        # The kwarg must be on the engine construction itself.
        start = ENV_PY.index("async_engine_from_config(")
        window = ENV_PY[start : start + 500]
        assert "connect_args" in window, "connect_args is computed but not passed to the engine"

    def test_a_direct_connection_is_left_alone(self):
        """
        THE VACUITY GUARD: the args must be CONDITIONAL. Disabling the statement cache
        unconditionally would give up the cache on every local migration against a direct
        Postgres for no reason, and would hide whether the detection works at all.
        """
        # Asserted on the assignment itself rather than "near the string 6543", which the
        # explanatory comment above it would satisfy for the wrong reason.
        assert "_CONNECT_ARGS = (" in ENV_PY
        start = ENV_PY.index("_CONNECT_ARGS = (")
        assignment = ENV_PY[start : ENV_PY.index(")", start) + 1]
        assert "if _VIA_POOLER else {}" in assignment, assignment

    def test_the_detection_handles_an_unset_url(self):
        """
        `database_url` is `os.environ.get(...)` and can be None — `":6543" in None` would raise
        at import time, which in this file means alembic cannot even load.
        """
        start = ENV_PY.index("_VIA_POOLER = ")
        line = ENV_PY[start : ENV_PY.index("\n", start)]
        assert "bool(database_url)" in line, line
