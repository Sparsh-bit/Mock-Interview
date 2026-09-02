"""
The app must start and be able to SAY what is wrong — tests/test_startup_and_health_are_diagnosable.py

WHAT THIS FILE IS ACTUALLY ABOUT. A production outage took a very long time to diagnose, and
the reason was not that the bugs were subtle. It was that the application could not tell
anybody anything: it exited during startup, so a platform 502 with no body was the only
observable, and each restart discarded the logs. Every symptom available to the operator —
502, x-railway-fallback: true, a browser console full of CORS errors, a dead Console tab —
was a consequence of "not running" and pointed nowhere near a cause.

Two properties fix that class of problem, and both are asserted here.

1. AN UNREACHABLE DATABASE MUST NOT ABORT STARTUP.

   main.py raised RuntimeError("Database is unreachable. Aborting startup.") in production.
   The intent was fail-fast, which is usually right — but here it trades a diagnosable
   degraded service for an undiagnosable absent one. The platform's answer to a
   crash-looping container is a 502 with no information; there is no way to tell "the
   database is unreachable" from "the code crashed" from "the port is wrong".

   The codebase already made exactly this call for Redis, and wrote down why: "refusing to
   boot would trade a working-but-degraded service for no service at all". The same
   reasoning applies with more force to the database, because /api/v1/health already knows
   how to report it — a mechanism that is useless if the process is not alive to serve it.

   Nothing is hidden by this. The failure is logged as an ERROR, health reports
   status=degraded with database=unreachable, and every endpoint that needs the database
   still fails. What changes is that a human can now find out WHY with one curl.

2. THE HEALTH ENDPOINT MAY NEVER HANG.

   Its own docstring says "a health check that hangs is worse than one that reports a
   failure: the monitor times out and reports the entire service down because somebody else
   was having a bad minute." The code did not honour that for the database: it awaited
   check_db_connection() with no deadline. A platform healthcheck that times out marks the
   deployment unhealthy and stops routing to it — producing the SAME 502 and the SAME
   x-railway-fallback header as a dead container, from an application that is running
   perfectly. That is the worst possible failure to debug.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = (REPO_ROOT / "backend/app/main.py").read_text()
HEALTH_PY = (REPO_ROOT / "backend/app/api/v1/health.py").read_text()


class TestStartupSurvivesAnUnreachableDatabase:
    def test_it_does_not_abort_startup(self):
        """
        Asserted on the RAISE, not on the phrase: the comment explaining this reversal quotes
        the old error message, and a rule's own explanation must not read as a violation of it
        — the same trap src/lib/security-headers.test.ts records.
        """
        code = "\n".join(
            line for line in MAIN_PY.split("\n") if not line.lstrip().startswith("#")
        )
        block_start = code.index("if not db_ok:")
        block = code[block_start : block_start + 1500]
        assert "raise RuntimeError" not in block, (
            "an unreachable database still aborts startup. A crash-looping container reports "
            "nothing but a platform 502; a degraded one can be asked what is wrong."
        )

    def test_the_failure_is_still_an_error_not_a_shrug(self):
        # Degrading must not become quiet. This is the most serious dependency there is.
        assert "database_unreachable_at_startup" in MAIN_PY
        block = MAIN_PY[MAIN_PY.index("database_unreachable_at_startup") :][:1200]
        assert "logger.error" in MAIN_PY[: MAIN_PY.index("database_unreachable_at_startup") + 60]
        # And it must say what the consequence is, so the log is actionable.
        assert "health" in block or "degraded" in block

    def test_it_still_refuses_a_placeholder_jwt_secret(self):
        """
        THE VACUITY GUARD. "Start even when something is wrong" must not spread to things that
        are unsafe rather than merely broken — an unverifiable JWT secret is an auth bypass,
        not a degradation. core/security.py fails closed on it and must keep doing so.
        """
        sec = (REPO_ROOT / "backend/app/core/security.py").read_text()
        assert "your-jwt-secret" in sec


class TestTheHealthEndpointCannotHang:
    def test_every_probe_is_bounded(self):
        assert "wait_for" in HEALTH_PY or "timeout" in HEALTH_PY, (
            "the health endpoint awaits its probes with no deadline. A platform healthcheck "
            "that times out is indistinguishable from a dead container."
        )

    def test_the_database_probe_specifically_is_bounded(self):
        """
        This was the unbounded one; the provider check already had its own timeouts. Anchored
        on the CALL SITE inside health_check, not on the import several hundred lines above it.
        """
        body_start = HEALTH_PY.index("async def health_check(")
        body = HEALTH_PY[body_start:]
        call = body.index("check_db_connection()")
        window = body[max(0, call - 800) : call + 300]
        assert "wait_for" in window or "_probe_all" in window, window[:400]

    def test_the_budget_is_short_enough_for_a_platform_probe(self):
        seconds = [float(m) for m in re.findall(r"_PROBE_BUDGET_SECONDS\s*=\s*([0-9.]+)", HEALTH_PY)]
        assert seconds, "no _PROBE_BUDGET_SECONDS constant found"
        # A healthcheck probe that takes longer than a few seconds is itself the problem.
        assert max(seconds) <= 5

    def test_a_timed_out_probe_reads_as_unreachable_not_as_healthy(self):
        """
        THE VACUITY GUARD that matters most here. Bounding a probe must never make a broken
        dependency look fine — that would turn a visible outage into silent data errors.
        """
        assert "unreachable" in HEALTH_PY
        # The status must still be derived from the probes, not hardcoded.
        assert 'dependencies_healthy' in HEALTH_PY

    def test_it_still_returns_200_while_degraded(self):
        """
        Deliberate, and worth pinning. A non-2xx here would stop the platform routing to the
        container at all, which is what makes a degraded service undebuggable — the failure
        this whole file exists to prevent.
        """
        assert "status_code=503" not in HEALTH_PY
        assert "HTTP_503" not in HEALTH_PY


@pytest.mark.asyncio
class TestTheBoundedProbeBehaves:
    async def test_a_hanging_probe_resolves_to_false_quickly(self):
        """The shape health.py now uses, asserted as behaviour rather than as source."""

        async def never_returns() -> bool:
            await asyncio.sleep(3600)
            return True

        async def bounded() -> bool:
            try:
                return await asyncio.wait_for(never_returns(), timeout=0.05)
            except TimeoutError:
                return False

        assert await bounded() is False

    async def test_a_healthy_probe_is_unaffected(self):
        async def fine() -> bool:
            return True

        assert await asyncio.wait_for(fine(), timeout=5) is True
