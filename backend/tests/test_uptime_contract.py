"""
The contract docs/UPTIME.md and monitoring/checks/health.check.ts are built on.

THE RUNBOOK'S CENTRAL CLAIM IS THAT `/api/v1/health` RETURNS 200 WHILE DEGRADED, and that
therefore every monitor must assert on the BODY rather than the status code. If that ever
stopped being true — somebody makes the endpoint 503 on a dependency failure, which is a
perfectly reasonable-looking change — then the monitors are still correct but the runbook's
explanation is wrong, and the next person reads a page that argues for something the code no
longer does.

The reverse is worse and is the one this really guards: if `dependencies_healthy` is renamed
or stops being the AND of the three, EVERY MONITOR SILENTLY STOPS WORKING. A JSONPath
assertion against a field that no longer exists does not error — Checkly and UptimeRobot both
treat "the phrase is absent" as a failure, so the checks would fire constantly, be muted, and
then the real outage would arrive unwatched.

So the field names here are a published interface, not an implementation detail.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

#: The exact JSONPaths asserted in monitoring/checks/health.check.ts. Written out rather than
#: parsed out of the TypeScript, because the point is that changing either side should require
#: changing the other DELIBERATELY.
MONITORED_FIELDS = ("status", "dependencies_healthy")


async def _health():
    """Call the endpoint. Dependency results are steered by monkeypatching health_api."""
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            timeout=30.0,
        ) as ac,
    ):
        return await ac.get("/api/v1/health")


@pytest.mark.asyncio
class TestTheHealthEndpointIsShapedTheWayTheMonitorsExpect:
    async def test_the_monitored_fields_exist(self):
        body = (await _health()).json()
        for field in MONITORED_FIELDS:
            assert field in body, (
                f"`{field}` is asserted on by monitoring/checks/health.check.ts and by the "
                f"UptimeRobot keyword in docs/UPTIME.md. Renaming it does not fail anything "
                f"here except this test — it makes every uptime monitor fire forever."
            )

    async def test_it_names_each_dependency_separately(self):
        """
        The runbook routes alerts differently per dependency: database or Supabase down is a
        page-somebody event; Redis down is a same-day one, because the app keeps serving while
        rate limiting fails open and the AI spend cap goes per-process. That triage is only
        possible if the body says which one broke.
        """
        body = (await _health()).json()
        for dependency in ("database", "redis", "supabase"):
            assert dependency in body

    async def test_dependencies_healthy_is_the_and_of_the_three(self):
        # Not a fourth independent probe. If it ever became one it could report `true` while
        # a named dependency said `unreachable`, and the alert would contradict itself.
        body = (await _health()).json()
        expected = all(
            body[d] == "connected" for d in ("database", "redis", "supabase")
        )
        assert body["dependencies_healthy"] is expected

    async def test_a_degraded_service_still_answers_200(self, monkeypatch):
        """
        THE ASSERTION THE WHOLE RUNBOOK RESTS ON.

        A status-code-only monitor shows a green tick here while nobody can sign in. That is
        why every check in monitoring/ asserts on the body, and why docs/UPTIME.md tells the
        UptimeRobot user to pick "Keyword" and not "HTTP(s)".

        If somebody changes this endpoint to 503 on failure, this test fails and the runbook
        needs rewriting with it — which is the point.
        """
        from app.api.v1 import health as health_api

        async def unreachable() -> bool:
            return False

        monkeypatch.setattr(health_api, "check_db_connection", unreachable)

        response = await _health()
        assert response.status_code == 200, (
            "The health endpoint now fails closed. That may well be an improvement, but "
            "docs/UPTIME.md and monitoring/checks/health.check.ts both explain at length why "
            "a body assertion is required BECAUSE it returns 200 when degraded. Update them."
        )
        body = response.json()
        assert body["database"] == "unreachable"
        assert body["dependencies_healthy"] is False
        # And `status` stays "ok", which is exactly the trap: the shallow check passes.
        assert body["status"] == "ok"

    async def test_it_needs_no_authentication(self):
        # A monitor has no token, and giving one a standing credential for a real account is
        # not worth the coverage — see "What NOT to monitor" in docs/UPTIME.md.
        response = await _health()
        assert response.status_code == 200
