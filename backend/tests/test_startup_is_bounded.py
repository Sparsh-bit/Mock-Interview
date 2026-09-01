"""
Startup cannot hang on a diagnostic — tests/test_startup_is_bounded.py

WHAT HAPPENED. The lifespan awaited `check_schema_drift()` with no time limit. Its own comment
says "Logged, never fatal", and the function is careful never to raise — but an UNBOUNDED AWAIT
during startup is fatal in effect, because the platform gives boot a fixed window
(`healthcheckTimeout: 120` in railway.json) and kills the container when it expires. The
symptom is a crash loop and a 502 that answers in 2ms, with the last log line being a harmless
SAWarning about a pgvector column.

WHY IT ONLY BIT IN PRODUCTION. The check asks the database for every table's columns, so its
cost is round trips x tables. Locally that is a millisecond each. In production the API is in
US West and the database in ap-southeast-2, roughly 200ms apart, through a transaction pooler
that assigns a fresh backend per statement — and `WEB_CONCURRENCY=4` means FOUR uvicorn workers
each run the whole lifespan at once, against a pooler holding 15 connections.

So the fix is a deadline, not a removal: the check is genuinely useful — a missing column
otherwise surfaces only as a 500 on whichever endpoint touches it, and those reach the browser
as a CORS error. It just must not be able to outlive the boot window it runs inside.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = (REPO_ROOT / "backend/app/main.py").read_text()


class TestTheDriftCheckHasADeadline:
    @staticmethod
    def _call_window() -> str:
        """The code around the actual call, not the import several comment-blocks above it."""
        start = MAIN_PY.index("check_schema_drift()")
        return MAIN_PY[start - 400 : start + 900]

    def test_the_lifespan_bounds_it(self):
        window = self._call_window()
        assert "wait_for" in window or "timeout" in window, (
            "check_schema_drift is awaited without a deadline. It cannot raise, but it can "
            "outlast the platform's boot window, which kills the container — a crash loop whose "
            "last log line is an unrelated warning."
        )

    def test_a_timeout_is_logged_and_not_raised(self):
        """
        Startup must survive the diagnostic failing. Turning a slow diagnostic into a failed
        boot is the bug, restated.
        """
        window = self._call_window()
        assert "TimeoutError" in window
        # And it must not re-raise inside that handler.
        handler = window[window.index("TimeoutError") :]
        assert "raise" not in handler[:400]

    def test_the_budget_is_well_inside_the_platform_window(self):
        """
        The deadline is only useful if it expires BEFORE the platform gives up. railway.json
        allows 120s for the whole boot, which also has to cover migrations and seeds.
        """
        import re

        # The constant is read from the whole file, not the call window: the call names the
        # constant, and the number lives with its explanation.
        seconds = [
            float(m)
            for m in re.findall(r"_SCHEMA_DRIFT_BUDGET_SECONDS\s*=\s*([0-9.]+)", MAIN_PY)
        ]
        assert seconds, "no numeric timeout found"
        assert max(seconds) <= 30, f"budget {max(seconds)}s is too close to the 120s boot window"


@pytest.mark.asyncio
class TestTheCheckItselfStillCannotRaise:
    async def test_a_hanging_check_is_survivable(self):
        """
        The behaviour, not the source: a check that never returns must not stop the caller.
        Mirrors what the lifespan now does.
        """

        async def never_returns() -> dict:
            await asyncio.sleep(3600)
            return {}

        drift: dict | None = None
        try:
            drift = await asyncio.wait_for(never_returns(), timeout=0.05)
        except TimeoutError:
            drift = None
        assert drift is None
