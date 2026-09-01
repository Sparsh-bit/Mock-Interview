"""
The boot lock is skipped, loudly, behind a transaction pooler — tests/test_boot_lock_pooler.py

THE ASSUMPTION THAT WAS FALSE. `boot_lock`'s docstring said the lock "is SESSION-scoped and
taken on a dedicated connection, so it survives the subprocesses the caller runs under it".
That holds against Postgres directly. It does NOT hold through Supabase's transaction-mode
pooler on port 6543: there, a "connection" is handed a server backend per TRANSACTION, so
`pg_try_advisory_lock` can be taken on one backend, the migration can run on another, and
`pg_advisory_unlock` can land on a third. The lock protects nothing, and the failure is silent.

Worse than silent, it can be fatal. The container's CMD is `boot.py && uvicorn`, so anything
that makes the lock loop or raise means uvicorn never starts and the platform serves 502
"Application failed to respond" with no application error to read.

WHY SKIP RATHER THAN FIX THE LOCK. A session-scoped lock cannot be made to work through
transaction pooling — that is what the mode means. The honest options are to skip it or to open
a second, non-pooled connection just for boot, and the second needs a direct database URL that
a deployment may not have (Supabase's direct host is IPv6-only without the IPv4 add-on). So it
is skipped, and said out loud, which is what this codebase does everywhere else that a
guarantee is unavailable: degrade visibly rather than pretend.

WHAT IS LOST, STATED PLAINLY. With one replica: nothing — there is no second booter to race.
With several replicas behind a pooler, concurrent migrations become possible again, which is
the exact failure the lock was written for. That case needs a direct URL for boot, and the
warning says so.
"""

from __future__ import annotations

import pytest

from app.db import boot_lock as mod


class TestItKnowsWhenTheLockCannotWork:
    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+asyncpg://u:p@aws-0-ap-south-1.pooler.supabase.com:6543/postgres",
            "postgresql+asyncpg://u:p@host:5432/db?pgbouncer=true",
        ],
    )
    def test_a_transaction_pooler_is_recognised(self, url):
        assert mod.lock_is_meaningless(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            # Direct Postgres.
            "postgresql+asyncpg://u:p@db.abcdefgh.supabase.co:5432/postgres",
            # Supabase's SESSION pooler: a client keeps one backend for the whole session, so a
            # session-scoped lock behaves exactly as it does against Postgres directly.
            "postgresql+asyncpg://u:p@aws-0-ap-south-1.pooler.supabase.com:5432/postgres",
            "postgresql+asyncpg://u:p@localhost:5433/interviewos",
        ],
    )
    def test_a_direct_or_session_connection_keeps_the_lock(self, url):
        """
        THE VACUITY GUARD. A detector that returned True everywhere would disable the lock for
        every deployment, including the multi-replica ones it exists to protect.
        """
        assert mod.lock_is_meaningless(url) is False


@pytest.mark.asyncio
class TestItYieldsWithoutTouchingTheDatabase:
    async def test_it_yields_true_and_opens_no_connection(self, monkeypatch):
        """
        The whole point: boot work must still happen, and it must not depend on a lock the
        pooler cannot honour. Opening a connection at all is the failure — that is what could
        hang and take uvicorn down with it.
        """
        monkeypatch.setattr(mod, "lock_is_meaningless", lambda _url: True)

        class _ExplodingEngine:
            """AsyncEngine.connect is read-only, so the engine itself is replaced."""

            def connect(self):
                raise AssertionError("opened a connection despite the lock being unusable")

        from app.db import session as session_mod

        monkeypatch.setattr(session_mod, "engine", _ExplodingEngine())

        async with mod.boot_lock(wait_seconds=5) as acquired:
            assert acquired is True

    async def test_it_warns_so_the_skip_is_in_the_deploy_log(self, monkeypatch):
        """
        A silent skip would be the same class of bug as the broken lock it replaces: a
        guarantee quietly not being provided.

        THE LOGGER IS RECORDED RATHER THAN THE OUTPUT CAPTURED. Both caplog and capsys are
        unreliable here — structlog's configuration is process-wide and other tests in the
        suite reconfigure it, so this passed alone and failed in the full run. Asserting on the
        call is deterministic and is what the test is actually about.
        """
        monkeypatch.setattr(mod, "lock_is_meaningless", lambda _url: True)

        events: list[str] = []

        class _Recorder:
            def warning(self, event: str, **_kw) -> None:
                events.append(event)

            def __getattr__(self, _name):  # info/error/debug are irrelevant here
                return lambda *a, **k: None

        monkeypatch.setattr(mod, "logger", _Recorder())

        async with mod.boot_lock(wait_seconds=5):
            pass

        assert "boot_lock_skipped_behind_transaction_pooler" in events
