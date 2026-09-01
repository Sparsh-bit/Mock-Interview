"""
The first thing startup does cannot hang — tests/test_startup_db_probe_bounded.py

WHY THIS IS THE WORST OF THE UNBOUNDED CALLS. `check_db_connection()` is the FIRST network
call in the lifespan, and it had no timeout of any kind: it opened a session and ran SELECT 1.
Its `except Exception` handler makes it look safe, and for a REFUSED connection it is — the
refusal raises and is logged. But a connection that HANGS never raises, so:

  * startup never finishes
  * the platform's boot window (healthcheckTimeout: 120 in railway.json) expires
  * the container is killed from outside
  * and because nothing raised, NOTHING IS LOGGED about the database at all

The result is a crash loop whose deploy log ends after the last unrelated warning, a public
URL answering 502 with `x-railway-fallback: true`, and a browser console full of CORS errors.
Every visible symptom points somewhere other than the cause. That is what makes an unbounded
network call inside a fixed boot window a bug in its own right, independent of why the
connection was slow.

A hang has many ordinary causes: a firewall, a region change, an unreachable pooler port, a
saturated pooler, or a URL pointing at a host that silently drops packets rather than refusing.

So the RULE, applied as a class rather than one instance at a time: every network call in
startup has a deadline, and every deadline failure says what it was trying to reach. The
schema-drift check was the other instance and is already bounded.

THE HOST IS LOGGED BEFORE THE ATTEMPT, credentials stripped. "Cannot reach the database" is
only actionable if you know which database it meant.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = (REPO_ROOT / "backend/app/main.py").read_text()


class TestTheProbeHasADeadline:
    @staticmethod
    def _window() -> str:
        start = MAIN_PY.index("check_db_connection()")
        return MAIN_PY[start - 1200 : start + 1600]

    def test_it_is_bounded(self):
        assert "wait_for" in self._window(), (
            "check_db_connection is awaited without a deadline. A refused connection raises "
            "and is logged; a HANGING one never raises, so the container is killed by the "
            "platform with nothing logged about the database at all."
        )

    def test_a_timeout_is_named_not_silent(self):
        w = self._window()
        assert "TimeoutError" in w
        # It must produce a distinct, searchable event — not be folded into the generic path.
        assert re.search(r"database_connect_timed_out|db_connect_timed_out", w), w[:200]

    def test_the_budget_is_well_inside_the_boot_window(self):
        seconds = [
            float(m) for m in re.findall(r"_DB_CONNECT_BUDGET_SECONDS\s*=\s*([0-9.]+)", MAIN_PY)
        ]
        assert seconds, "no _DB_CONNECT_BUDGET_SECONDS constant found"
        # 120s covers migrations, seeds and the whole lifespan. A probe may not eat it.
        assert max(seconds) <= 30

    def test_a_timeout_is_still_treated_as_unreachable(self):
        """
        THE VACUITY GUARD. Bounding it must not turn "cannot reach the database" into "carry
        on regardless" — serving requests with no database produces 500s on every endpoint,
        which reach the browser as CORS errors. Production must still refuse to start, but now
        with a named reason instead of a silent kill.
        """
        w = self._window()
        assert "db_ok = False" in w or "db_ok=False" in w, w[:300]


class TestTheTargetIsLoggedWithoutCredentials:
    def test_the_host_is_logged_before_connecting(self):
        assert "database_connecting" in MAIN_PY, (
            '"cannot reach the database" is only actionable if the log says WHICH database.'
        )

    def test_credentials_are_stripped(self):
        """A DSN carries a password. It must never reach a log line."""
        helper = MAIN_PY[MAIN_PY.index("def _db_target"):] if "_db_target" in MAIN_PY else ""
        assert helper, "expected a _db_target helper that redacts the DSN"
        head = helper[:700]
        assert "@" in head, "must split on @ to drop the userinfo"


@pytest.mark.asyncio
class TestTheRedactionActuallyWorks:
    async def test_only_host_and_port_survive(self):
        from app.main import _db_target

        target = _db_target(
            "postgresql+asyncpg://postgres.abc:SuperSecret123@aws-0-ap-southeast-2."
            "pooler.supabase.com:6543/postgres"
        )
        assert "SuperSecret123" not in target
        assert "postgres.abc" not in target
        assert "aws-0-ap-southeast-2.pooler.supabase.com:6543" in target

    async def test_a_malformed_url_does_not_raise(self):
        # This runs while diagnosing a failure. It must not become the failure.
        from app.main import _db_target

        for bad in ("", "not a url", "postgresql://", "host-only"):
            assert isinstance(_db_target(bad), str)
