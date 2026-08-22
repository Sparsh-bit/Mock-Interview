"""
The report budget covers queueing too, not only generating — tests/test_report_budget.py

REPORTED WITH A SCREENSHOT, mid-launch: "Report Unavailable — Request timed out after
120000ms."

The comment in generate_report said exactly the right thing and the code did the opposite:

    # Waiting counts against the same wall-clock budget as generating, deliberately:
    # a candidate who has been queued for 50 seconds is better served the honest
    # unscored placeholder with a retry than a request that hangs past the gateway.
    async with _report_slots:
        await asyncio.wait_for(generate_structured(...), timeout=report_ai_budget_seconds())

`async with _report_slots` was OUTSIDE the `wait_for`. So generation was bounded and
ACQUIRING A SLOT was bounded by nothing. Four slots at roughly 21 seconds a report means the
fifth caller waits ~21s, the ninth ~42s — and a queue of a dozen, which is exactly what a
cohort finishing their interviews within a few minutes of each other produces, ran straight
past the client's 120-second timeout with no response at all.

The failure mode is the worst available: not a slow report, not a degraded report, but no
response, on the screen the candidate cares most about, at the moment the product is busiest.

Both are inside the timeout now, so a request that cannot be served within the budget returns
the honest unscored placeholder with a retry — which every other failure branch in that
function already did.

These are structural assertions. Reproducing the real thing needs four concurrent live report
generations against a paid provider; what this catches is the regression, which is somebody
moving that `async with` back out during a refactor while every test still passes.
"""

from __future__ import annotations

import ast
import inspect

from app.api.v1 import reports


def _generate_report_source() -> str:
    return inspect.getsource(reports.generate_report)


class TestTheSemaphoreIsInsideTheTimeout:
    def test_the_slot_is_acquired_inside_the_budget(self):
        """
        THE ONE THAT WOULD HAVE CAUGHT IT.

        Parsed rather than grepped: `async with _report_slots` and `asyncio.wait_for` both
        still appear in the source whichever way round they are nested, so a string search
        cannot tell the fixed code from the broken code. The AST can.
        """
        tree = ast.parse(inspect.getsource(reports))
        target = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "generate_report"
        )

        # Every `async with` that mentions _report_slots, and every wait_for call.
        slot_withs = [
            n for n in ast.walk(target)
            if isinstance(n, ast.AsyncWith)
            and "_report_slots" in ast.unparse(n.items[0].context_expr)
        ]
        assert slot_withs, "the concurrency cap is gone entirely"

        waits = [
            n for n in ast.walk(target)
            if isinstance(n, ast.Call)
            and ast.unparse(n.func).endswith("wait_for")
        ]
        assert waits, "report generation is no longer bounded by a timeout at all"

        # THE INVARIANT, STATED THE SIMPLE WAY ROUND.
        #
        # In the broken version the `async with _report_slots` CONTAINED the `wait_for`, so the
        # slot was taken before the clock started. In the fixed version the slot lives inside a
        # coroutine that `wait_for` wraps, so no slot-acquiring `async with` contains a
        # `wait_for` at all. That is the whole difference, and it is one assertion.
        for sw in slot_withs:
            enclosed = [
                w for w in waits
                if sw.lineno <= w.lineno
                and (sw.end_lineno or sw.lineno) >= (w.end_lineno or w.lineno)
            ]
            assert not enclosed, (
                "the report slot is acquired OUTSIDE the timeout: queue time is unbounded, so "
                "a queued request can outlive the client. Move the `async with _report_slots` "
                "inside the coroutine that asyncio.wait_for wraps."
            )

    def test_the_budget_stays_inside_the_gateway_window(self):
        """
        The whole point of a budget here is the host's ~100s gateway. A budget above it means
        the gateway kills the request first and the candidate gets no response rather than a
        degraded one.
        """
        assert reports.report_ai_budget_seconds() <= 90.0

    def test_a_timeout_still_degrades_rather_than_failing(self):
        # The behaviour that makes bounding safe: exceeding the budget produces the honest
        # unscored report with a retry, not a 500.
        src = _generate_report_source()
        assert "except (AIProviderUnavailableError, TimeoutError)" in src
        assert "_classify_failure(exc)" in src

    def test_the_concurrency_cap_survives(self):
        # Bounding the wait must not be done by removing the queue. Four in-flight ~17k-token
        # prompts is the memory ceiling, and unbounded concurrency trades a database outage for
        # a provider rate-limit storm.
        assert reports._REPORT_CONCURRENCY >= 1
        assert "_report_slots" in _generate_report_source()
