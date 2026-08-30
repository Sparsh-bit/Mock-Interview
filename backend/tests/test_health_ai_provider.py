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
