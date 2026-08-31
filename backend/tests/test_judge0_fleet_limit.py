"""
The shared free Judge0 instance is not hammered — tests/test_judge0_fleet_limit.py

WHY THIS EXISTS. `CODE_EXEC_PROVIDER=judge0` defaults to the PUBLIC Judge0 CE instance: free,
no key, and shared with everybody else on the internet. The only limit in front of it was
`RATE_LIMIT_CODE_EXEC_PER_MINUTE`, which is keyed PER USER — so it caps one candidate at 20 a
minute and says nothing at all about 200 of them. Two hundred candidates in coding rounds is
a load nobody agreed to put on a free shared service, and the way it ends is 429s and a
blocked IP for the whole deployment, not a polite slowdown.

COUNTED IN REQUESTS, for the same reason the burst rung is: a Judge0 CE call costs $0.00, so
no money cap can see it. `AI_DAILY_BUDGET_USD` never moves.

THE COUNTER IS SHARED WITH THE BURST RUNG rather than reimplemented — same Redis INCR, same
per-process fallback, same reserve-before-the-call ordering. See app/db/daily_counter.py.

AND IT ONLY APPLIES TO THE FREE INSTANCE. With `JUDGE0_API_KEY` set the capacity has been
paid for, and a cap meant to protect a free service must not throttle a paid one.
"""

from __future__ import annotations

import pytest

from app.api.v1 import code as code_api
from app.db import daily_counter


@pytest.fixture(autouse=True)
def _clear_tallies():
    daily_counter._tallies.clear()
    yield
    daily_counter._tallies.clear()


@pytest.fixture
def _no_redis(monkeypatch):
    """
    Force the local-only path — the branch that has to work when Redis blinks, which caps a
    single process rather than the fleet. Degraded, and better than no cap at all.
    """
    def boom():
        raise RuntimeError("redis unavailable")
    monkeypatch.setattr("app.db.redis.get_redis", boom)


@pytest.mark.asyncio
class TestTheSharedCounter:
    async def test_a_fresh_day_has_budget(self, _no_redis):
        assert await daily_counter.has_budget("judge0", 100) is True

    async def test_it_refuses_once_the_allowance_is_spent(self, _no_redis):
        for _ in range(5):
            await daily_counter.reserve("judge0")
        assert await daily_counter.has_budget("judge0", 5) is False
        # THE VACUITY GUARD. A has_budget that returned False unconditionally would satisfy
        # the line above and would disable code execution permanently.
        assert await daily_counter.has_budget("judge0", 6) is True

    async def test_zero_disables_the_cap(self, _no_redis):
        for _ in range(50):
            await daily_counter.reserve("judge0")
        assert await daily_counter.has_budget("judge0", 0) is True

    async def test_the_names_are_separate_budgets(self, _no_redis):
        """
        One counter serving two callers must not let code execution spend the burst rung's
        allowance. Same mechanism, independent tallies.
        """
        for _ in range(5):
            await daily_counter.reserve("judge0")
        assert await daily_counter.used_today("judge0") == 5
        assert await daily_counter.used_today("ai:rung") == 0


@pytest.mark.asyncio
class TestTheEndpointRefusesWithoutCallingOut:
    """
    Refusing locally is the entire point: a call that will be 429'd is worse than no call,
    because it still costs a round trip and it still counts against the shared instance.
    """

    @staticmethod
    def _explode_on_http(monkeypatch):
        """Any outbound HTTP is a test failure, so prove the gate came first."""
        def boom(*args, **kwargs):
            raise AssertionError("Judge0 was called despite the daily limit being spent")
        monkeypatch.setattr(code_api.httpx, "AsyncClient", boom)

    async def test_it_does_not_call_judge0_once_the_limit_is_spent(
        self, monkeypatch, _no_redis
    ):
        monkeypatch.setattr(code_api.settings, "JUDGE0_DAILY_REQUEST_LIMIT", 3)
        monkeypatch.setattr(code_api.settings, "JUDGE0_API_KEY", "")
        self._explode_on_http(monkeypatch)

        for _ in range(3):
            await daily_counter.reserve("judge0")

        request = code_api.CodeExecuteRequest(language="python", source="print(1)", stdin="")
        with pytest.raises(code_api._RunnerUnavailable):
            await code_api._run_on_judge0("python", request)

    async def test_a_call_under_the_limit_is_attempted(self, monkeypatch, _no_redis):
        """
        THE VACUITY GUARD for the gate. If it refused everything the test above would still
        pass and code execution would be dead.
        """
        monkeypatch.setattr(code_api.settings, "JUDGE0_DAILY_REQUEST_LIMIT", 3)
        monkeypatch.setattr(code_api.settings, "JUDGE0_API_KEY", "")

        called = []

        class _FakeClient:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, **kwargs):
                called.append(url)
                raise AssertionError("reached the network, which is enough for this test")

        monkeypatch.setattr(code_api.httpx, "AsyncClient", _FakeClient)

        request = code_api.CodeExecuteRequest(language="python", source="print(1)", stdin="")
        with pytest.raises(AssertionError, match="reached the network"):
            await code_api._run_on_judge0("python", request)
        assert called, "the gate refused a call that was inside its allowance"

    async def test_the_attempt_is_reserved_before_the_call(self, monkeypatch, _no_redis):
        """
        Reserve BEFORE, not on success. Counting on success lets a burst of concurrent
        requests all read one-below-the-limit and all proceed; counting a failed attempt is
        the conservative error and 'must not exceed' is the requirement.
        """
        monkeypatch.setattr(code_api.settings, "JUDGE0_DAILY_REQUEST_LIMIT", 10)
        monkeypatch.setattr(code_api.settings, "JUDGE0_API_KEY", "")

        def boom(*args, **kwargs):
            raise RuntimeError("network down")
        monkeypatch.setattr(code_api.httpx, "AsyncClient", boom)

        request = code_api.CodeExecuteRequest(language="python", source="print(1)", stdin="")
        with pytest.raises(Exception):  # noqa: B017 - any failure; the tally is the assertion
            await code_api._run_on_judge0("python", request)

        assert await daily_counter.used_today("judge0") == 1

    async def test_a_paid_key_is_not_capped_by_the_free_tier_guard(
        self, monkeypatch, _no_redis
    ):
        """
        The guard protects a FREE shared service. With JUDGE0_API_KEY set the capacity is
        bought, and throttling it would be the guard causing the outage it exists to prevent.
        """
        monkeypatch.setattr(code_api.settings, "JUDGE0_DAILY_REQUEST_LIMIT", 3)
        monkeypatch.setattr(code_api.settings, "JUDGE0_API_KEY", "a-real-rapidapi-key")

        for _ in range(99):
            await daily_counter.reserve("judge0")

        reached = []

        class _FakeClient:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, **kwargs):
                reached.append(url)
                raise RuntimeError("far enough")

        monkeypatch.setattr(code_api.httpx, "AsyncClient", _FakeClient)

        request = code_api.CodeExecuteRequest(language="python", source="print(1)", stdin="")
        with pytest.raises(Exception):  # noqa: B017
            await code_api._run_on_judge0("python", request)
        assert reached, "a paid Judge0 was throttled by the free-tier guard"
