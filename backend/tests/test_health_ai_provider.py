"""
The AI-provider check on /api/v1/health.

THE TWO THINGS THAT COULD GO WRONG HERE ARE BOTH EXPENSIVE, in different currencies.

  MONEY. `BaseAIProvider.health_check()` already existed and makes a REAL COMPLETION
  CALL — Anthropic sends `messages.create(max_tokens=1)`, and the GLM path goes
  through `complete()`, which is the whole billed route including the usage ledger.
  Wiring that into a health endpoint that docs/UPTIME.md has monitors hitting every
  three minutes is ~480 billable calls a day per provider, and it writes synthetic
  rows into the `ai_usage` ledger that docs/AI-COST-MODEL.md and every pricing
  decision are derived from. So the tests below assert that no completion path is
  reachable from here — not merely that the current code happens not to call one.

  TIME. A health endpoint that hangs is worse than one reporting a failure: the
  monitor times out and reports the whole service down because a third party had a
  bad minute. Two tests hold the endpoint to a deadline with a provider that never
  answers at all.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.services.ai import reachability


def _code_of(module) -> str:
    """Module source with every comment and string literal removed."""
    import io
    import tokenize
    from pathlib import Path

    source = Path(module.__file__ or "").read_text()
    kept: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return " ".join(kept)


@pytest.fixture(autouse=True)
def _no_cached_result():
    reachability.reset_cache()
    yield
    reachability.reset_cache()


@pytest.fixture()
def one_provider(monkeypatch):
    """A single configured provider, so the probe count is unambiguous."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")


# ── It must never cost anything ──────────────────────────────────────────────


class TestItCannotSpendMoney:
    def test_it_probes_the_model_list_and_never_a_completion(self, one_provider):
        """
        `/models` runs no inference, is billed at nothing, and sits under a far more
        generous rate limit than completions — while still being AUTHENTICATED, so it
        proves the key is accepted. A plain TCP probe would prove only connectivity,
        and "reachable with a dead key" is the outage that looks healthiest.
        """
        targets = reachability._targets()
        assert targets, "no provider configured for this test"
        for _name, url, _headers in targets:
            assert url.endswith("/models"), url
            for forbidden in ("/messages", "/chat/completions", "/completions"):
                assert forbidden not in url

    def test_it_does_not_import_or_call_the_provider_health_check(self):
        """
        Asserted against the SOURCE, because the tempting change is one line —
        `await provider.health_check()` reads like exactly the right thing to call and
        is the expensive mistake this module exists to avoid.

        AGAINST THE CODE, NOT THE FILE. The module explains at length why it does not
        call `health_check()` or `complete()`, so a raw-text assertion fails on the
        comment that documents the rule — the same trap `src/lib/security-headers.test.ts`
        records paying for. Strings and comments are stripped with `tokenize`, which
        cannot mispair a delimiter the way a regex can.
        """
        assert "health_check" not in _code_of(reachability)
        assert "get_ai_provider" not in _code_of(reachability)
        assert ".complete(" not in _code_of(reachability)

    async def test_a_probe_sends_no_request_body(self, one_provider, monkeypatch):
        """A GET with no body cannot be a completion, whatever the URL says."""
        seen: list[httpx.Request] = []

        async def capture(self, url, **kwargs):  # noqa: ANN001
            request = httpx.Request("GET", url, headers=kwargs.get("headers") or {})
            seen.append(request)
            return httpx.Response(200, request=request)

        monkeypatch.setattr(httpx.AsyncClient, "get", capture)
        await reachability.check_provider_chain(use_cache=False)

        assert seen
        for request in seen:
            assert request.method == "GET"
            assert not request.content

    async def test_repeated_calls_are_served_from_cache(self, one_provider, monkeypatch):
        """
        Without a cache, /api/v1/health is an amplifier: anything that can hit it can
        make this container open connections to Anthropic as fast as it likes. The TTL
        is longer than the monitor interval, so scheduled monitoring costs one probe.
        """
        calls = 0

        async def counting(self, url, **kwargs):  # noqa: ANN001
            nonlocal calls
            calls += 1
            return httpx.Response(200, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", counting)
        for _ in range(5):
            await reachability.check_provider_chain()
        assert calls == 1


# ── It must never hang ───────────────────────────────────────────────────────


class TestItStaysFast:
    async def test_a_provider_that_never_answers_does_not_hang_the_check(
        self, one_provider, monkeypatch
    ):
        """
        THE ONE THE BRIEF ASKS FOR. A provider that never responds must produce
        `unknown` inside the deadline, not a hung request.
        """

        async def never_answers(self, url, **kwargs):  # noqa: ANN001
            await asyncio.sleep(3600)

        monkeypatch.setattr(httpx.AsyncClient, "get", never_answers)

        started = time.monotonic()
        result = await reachability.check_provider_chain(use_cache=False)
        elapsed = time.monotonic() - started

        assert elapsed < reachability.TOTAL_TIMEOUT_SECONDS + 1.0, (
            f"the provider check took {elapsed:.1f}s against a provider that never "
            f"answers; it must be bounded by TOTAL_TIMEOUT_SECONDS"
        )
        assert set(result.values()) == {"unknown"}

    async def test_the_health_endpoint_itself_stays_fast_when_a_provider_hangs(
        self, one_provider, monkeypatch
    ):
        """
        The end-to-end version, and the one that matters: a monitor timing out on
        /api/v1/health would report the WHOLE SERVICE down because a third party was
        slow. The other dependency probes are stubbed so this measures the provider
        check and nothing else.
        """
        from app.api.v1 import health as health_api

        async def never_answers(self, url, **kwargs):  # noqa: ANN001
            await asyncio.sleep(3600)

        async def instantly_true() -> bool:
            return True

        monkeypatch.setattr(httpx.AsyncClient, "get", never_answers)
        monkeypatch.setattr(health_api, "check_db_connection", instantly_true)
        monkeypatch.setattr(health_api, "check_redis_connection", instantly_true)
        monkeypatch.setattr(health_api, "_check_supabase_connection", instantly_true)

        started = time.monotonic()
        body = await health_api.health_check()
        elapsed = time.monotonic() - started

        assert elapsed < 5.0, f"/api/v1/health took {elapsed:.1f}s with a hanging provider"
        assert body["status"] == "ok"
        assert body["ai_providers"] == {"anthropic": "unknown"}

    async def test_unknown_is_not_cached(self, one_provider, monkeypatch):
        """
        Caching a non-answer for four minutes would keep reporting it long after the
        provider recovered — a stale "we do not know" is worse than probing again.
        """
        calls = 0

        async def slow_then_fine(self, url, **kwargs):  # noqa: ANN001
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.sleep(3600)
            return httpx.Response(200, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", slow_then_fine)
        assert set((await reachability.check_provider_chain()).values()) == {"unknown"}
        assert (await reachability.check_provider_chain())["anthropic"] == "reachable"


# ── It must report the right thing ───────────────────────────────────────────


class TestWhatItReports:
    async def test_a_rejected_key_is_unreachable_not_reachable(
        self, one_provider, monkeypatch
    ):
        """
        401/403 is the provider saying the credential is no longer good. Every
        completion will fail, so reporting "reachable" because the TCP connection
        succeeded would be the outage that looks healthiest.
        """

        async def unauthorised(self, url, **kwargs):  # noqa: ANN001
            return httpx.Response(401, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", unauthorised)
        result = await reachability.check_provider_chain(use_cache=False)
        assert result["anthropic"] == "unreachable"

    async def test_a_404_still_counts_as_reachable(self, one_provider, monkeypatch):
        """
        Base URLs are configured with and without a `/v1` suffix depending on the
        vendor, so the model-list path can legitimately 404. A routed HTTP response
        answers the question being asked — can this container reach the provider —
        and treating it as an outage would page somebody over a URL suffix.
        """

        async def not_found(self, url, **kwargs):  # noqa: ANN001
            return httpx.Response(404, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", not_found)
        assert (await reachability.check_provider_chain(use_cache=False))[
            "anthropic"
        ] == "reachable"

    async def test_a_dns_or_tls_failure_is_unreachable_not_unknown(
        self, one_provider, monkeypatch
    ):
        # Knowing it is broken is a different fact from not knowing, and only one of
        # them is worth telling somebody about.
        async def refused(self, url, **kwargs):  # noqa: ANN001
            raise httpx.ConnectError("nope", request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", refused)
        assert (await reachability.check_provider_chain(use_cache=False))[
            "anthropic"
        ] == "unreachable"

    async def test_it_reports_the_providers_this_deployment_would_actually_call(
        self, monkeypatch
    ):
        # Read from the same settings the request path reads, so it cannot describe a
        # chain nobody is using.
        from app.core.config import settings

        monkeypatch.setattr(settings, "AI_PROVIDER", "glm")
        monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "nvidia")
        monkeypatch.setattr(settings, "GLM_API_KEY", "k")
        monkeypatch.setattr(settings, "NVIDIA_API_KEY", "k")
        assert [name for name, _, _ in reachability._targets()] == ["glm", "nvidia"]

    async def test_a_provider_named_without_a_key_is_simply_absent(self, monkeypatch):
        # `not_configured` at the endpoint is a more useful answer than a probe that
        # was always going to fail.
        from app.core.config import settings

        monkeypatch.setattr(settings, "AI_PROVIDER", "anthropic")
        monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "")
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
        assert reachability._targets() == []
        assert await reachability.check_provider_chain(use_cache=False) == {}


class TestItDoesNotChangeTheAlerting:
    async def test_a_dead_provider_does_not_flip_dependencies_healthy(self, monkeypatch):
        """
        `dependencies_healthy` is what docs/UPTIME.md pages somebody on, and the three
        things in it share a property the model providers do not: if any of them is
        down, this service cannot serve at all. A provider being unreachable is a
        DEGRADATION — quizzes, existing reports, the dashboard, sign-in and payment all
        keep working, and the chain falls back to the standby by itself.

        Folding it in would page somebody at 3 a.m. for somebody else's incident that
        the fallback already handled.
        """
        from app.api.v1 import health as health_api
        from app.core.config import settings

        monkeypatch.setattr(settings, "AI_PROVIDER", "anthropic")
        monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "")
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "k")

        async def refused(self, url, **kwargs):  # noqa: ANN001
            raise httpx.ConnectError("nope", request=httpx.Request("GET", url))

        async def instantly_true() -> bool:
            return True

        monkeypatch.setattr(httpx.AsyncClient, "get", refused)
        monkeypatch.setattr(health_api, "check_db_connection", instantly_true)
        monkeypatch.setattr(health_api, "check_redis_connection", instantly_true)
        monkeypatch.setattr(health_api, "_check_supabase_connection", instantly_true)

        body = await health_api.health_check()
        assert body["ai_providers"] == {"anthropic": "unreachable"}
        assert body["dependencies_healthy"] is True, (
            "an unreachable model provider flipped the field the pager is wired to"
        )


# ── A day of monitoring, against the ledger ──────────────────────────────────


@pytest.mark.asyncio
class TestADayOfPollingCostsNothing:
    """
    The tests above prove no completion path is *reachable* from the probe. This proves
    the consequence that actually matters, by running the endpoint at the runbook's real
    cadence and watching the ledger writer rather than the source.

    docs/UPTIME.md check 1 polls every 3 minutes and check 2 every 5. Over 24 hours that
    is 480 + 288 = 768 requests to /api/v1/health, from two monitors, in two regions
    each — so 1536. Every one of them used to be a candidate for a billed completion and
    a synthetic row in `ai_usage`, the ledger docs/AI-COST-MODEL.md and every pricing
    decision are derived from.
    """

    #: 24h / 3min for check 1 and 24h / 5min for check 2, doubled for the two regions
    #: docs/UPTIME.md configures. Named rather than inlined so the arithmetic is checkable.
    POLLS_PER_DAY = (480 + 288) * 2

    async def test_no_row_is_even_attempted_over_a_full_day(self, one_provider, monkeypatch):
        """
        A tripwire on the ledger's own session, not a row count: this asserts nothing
        even *tries* to write, which a count cannot distinguish from a write that failed.
        """
        writes = 0

        def tripwire(*_a, **_k):
            nonlocal writes
            writes += 1
            raise AssertionError("the health check reached the AI usage ledger")

        monkeypatch.setattr("app.db.session.get_db_session", tripwire, raising=True)

        requests: list[str] = []

        async def fake_get(self, url, **kwargs):  # noqa: ANN001, ARG001
            requests.append(url)
            return httpx.Response(200, json={"data": []})

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

        for _ in range(self.POLLS_PER_DAY):
            await reachability.check_provider_chain()

        assert writes == 0, f"{writes} ledger writes from health polling alone"
        # And the outbound calls were model-list reads, never a completion.
        assert requests, "the probe made no request at all — the cache cannot be the reason"
        assert all(url.endswith("/models") for url in requests), (
            f"a non-/models endpoint was called: {sorted(set(requests))}"
        )

    async def test_the_cache_holds_the_outbound_count_to_the_ttl(self, one_provider, monkeypatch):
        """
        Zero cost is not only about which endpoint is called. Without the cache, /health
        is an amplifier: anything that can reach it opens connections to Anthropic as fast
        as it likes. At a 240s TTL a day of polling is 360 probes, not 1536 — and the
        1536 figure is only the *scheduled* traffic.
        """
        probes = 0
        clock = [0.0]

        async def counting_get(self, url, **kwargs):  # noqa: ANN001, ARG001
            nonlocal probes
            probes += 1
            return httpx.Response(200, json={"data": []})

        monkeypatch.setattr(httpx.AsyncClient, "get", counting_get)
        monkeypatch.setattr(reachability.time, "monotonic", lambda: clock[0])

        # 24h at check 1's 3-minute cadence, advancing a real clock.
        for _ in range(480):
            await reachability.check_provider_chain()
            clock[0] += 180.0

        # 86400s / 240s TTL = 360 ceiling; the 3-minute cadence lands on 240 exactly
        # every 4th poll, so the real figure is one per full TTL window.
        assert probes <= 360, f"{probes} outbound probes in a day — the cache is not holding"
        assert probes > 0

    async def test_the_endpoint_route_is_the_one_measured(self, one_provider, monkeypatch):
        """The two tests above call `check_provider_chain` directly. This confirms that is
        genuinely what a request to /api/v1/health reaches — otherwise they measure a
        function nothing calls."""
        from httpx import ASGITransport
        from httpx import AsyncClient as HTTPXClient

        from app.main import app

        seen: list[str] = []
        real_get = httpx.AsyncClient.get

        async def fake_get(self, url, **kwargs):  # noqa: ANN001
            # The test client is itself an httpx.AsyncClient, so an unconditional patch
            # intercepts the request to /api/v1/health and the app never runs at all.
            # Only outbound calls are faked; the in-process one is passed through.
            if "/api/v1/health" in str(url):
                return await real_get(self, url, **kwargs)
            seen.append(str(url))
            return httpx.Response(200, json={"data": []})

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

        async with (
            app.router.lifespan_context(app),
            HTTPXClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
                timeout=30.0,
            ) as ac,
        ):
            body = (await ac.get("/api/v1/health")).json()

        assert body["ai_providers"] == {"anthropic": "reachable"}
        assert any(url.endswith("/models") for url in seen), (
            f"/api/v1/health did not probe the model list: {seen}"
        )
        assert not any("messages" in url or "completions" in url for url in seen)
