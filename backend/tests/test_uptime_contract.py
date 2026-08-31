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
        # `status` used to stay the literal "ok" here, which was the trap: a body saying
        # `database: unreachable` and `dependencies_healthy: false` alongside a `status`
        # saying everything was fine. The 200 above is still the runbook's claim and still
        # deliberate — "the process answered" is what a status code means. `status` is not
        # a status code and no longer pretends to be one.
        assert body["status"] == "degraded"

    async def test_it_needs_no_authentication(self):
        # A monitor has no token, and giving one a standing credential for a real account is
        # not worth the coverage — see "What NOT to monitor" in docs/UPTIME.md.
        response = await _health()
        assert response.status_code == 200


@pytest.mark.asyncio
class TestTheDatabaseProbeAgainstARealClosedSocket:
    """
    Everything above steers the result by replacing `check_db_connection` with a coroutine
    that returns False. That proves the endpoint reports what the probe tells it; it proves
    nothing about the probe, which is the part that actually has to notice an outage.

    These sever the connection for real — a live engine pointed at a port with nothing
    listening — and run the unmodified `check_db_connection` against it.
    """

    @staticmethod
    def _dead_factory():
        """A session factory whose connections cannot succeed.

        127.0.0.1:1 is `tcpmux`; nothing binds it, so the kernel refuses the connection
        immediately rather than leaving the test to a DNS or TCP timeout. NullPool because
        a pooled engine would hold the failure and this must attempt a fresh connect.
        """
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        engine = create_async_engine(
            "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nosuchdb",
            poolclass=NullPool,
            connect_args={"timeout": 5},
        )
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    async def test_the_probe_itself_returns_false(self, monkeypatch):
        from app.db import session as db_session

        engine, factory = self._dead_factory()
        monkeypatch.setattr(db_session, "AsyncSessionFactory", factory)
        try:
            # The real function, not a stand-in. It must swallow the connection error and
            # answer False rather than propagating — a health check that raises is a 500,
            # and a 500 tells a keyword monitor nothing about which dependency broke.
            assert await db_session.check_db_connection() is False
        finally:
            await engine.dispose()

    async def test_the_endpoint_reports_it_and_still_answers(self, monkeypatch):
        """The whole path: closed socket -> probe -> body -> what a monitor reads."""
        from app.db import session as db_session

        engine, factory = self._dead_factory()
        monkeypatch.setattr(db_session, "AsyncSessionFactory", factory)
        try:
            response = await _health()
        finally:
            await engine.dispose()

        # Still 200. The runbook's central claim survives a real outage, not just a fake one.
        assert response.status_code == 200
        body = response.json()

        assert body["database"] == "unreachable"
        assert body["dependencies_healthy"] is False
        assert body["status"] == "degraded", (
            "A real, unfakeable database outage and the endpoint still says 'ok'. This is "
            "the exact condition docs/UPTIME.md pages somebody on."
        )

    async def test_a_reachable_database_still_reads_healthy(self):
        """The other direction. A probe hard-wired to False would pass every assertion above
        while making the endpoint useless."""
        body = (await _health()).json()
        assert body["database"] == "connected"
        # `status` tracks all three dependencies, so it is only "ok" when all three are.
        assert body["status"] == ("ok" if body["dependencies_healthy"] else "degraded")
