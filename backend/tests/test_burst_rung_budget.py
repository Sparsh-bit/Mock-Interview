"""
The free tier is not exceeded — tests/test_burst_rung_budget.py

WHY A REQUEST COUNT AND NOT A SPEND CAP. Groq's free plan is metered in REQUESTS PER DAY. A
call on it costs $0.00, so `AI_DAILY_BUDGET_USD` never moves and cannot bound it — the existing
money cap is structurally blind to this provider. Past the ceiling Groq answers 429: nothing
breaks, because the rung is only reached once both paid providers have already failed, but the
call fails after a round trip and leaves the account rate-limited, which the next health check
reports as a provider outage.

THE GATE IS SEPARATE FROM THE POLICY ON PURPOSE. `eligible_providers` answers "may this call
use a model we do not pay for" and is pure, synchronous and called directly by five other
tests. `rung_has_budget` answers "is there any allowance left" and is the only part that needs
Redis. Keeping them apart is what lets the policy stay trivially testable.
"""

from __future__ import annotations

import pytest

from app.services.ai import burst_rung


@pytest.fixture(autouse=True)
def _clear_local_tally():
    """Each test starts from zero — the module keeps a per-process count between calls."""
    burst_rung._local_requests.clear()
    yield
    burst_rung._local_requests.clear()


@pytest.fixture
def _no_redis(monkeypatch):
    """
    Force the local-only path.

    Redis is unavailable in most of this suite, and the fallback is the branch that actually
    has to work: it is what caps a single replica when Redis blinks, which is precisely when
    the paid providers are already struggling and the rung is being reached.
    """
    def boom():
        raise RuntimeError("redis unavailable")
    monkeypatch.setattr("app.db.redis.get_redis", boom)


@pytest.mark.asyncio
class TestTheCapHolds:
    async def test_a_fresh_day_has_budget(self, _no_redis):
        assert await burst_rung.rung_has_budget(2000) is True

    async def test_it_refuses_once_the_allowance_is_spent(self, _no_redis):
        for _ in range(5):
            await burst_rung.note_rung_request()
        assert await burst_rung.rung_has_budget(5) is False
        # THE VACUITY GUARD. A `rung_has_budget` that returned False unconditionally would
        # satisfy the assertion above and would also disable the fallback permanently.
        assert await burst_rung.rung_has_budget(6) is True

    async def test_the_boundary_is_exact(self, _no_redis):
        """
        `used < limit`, not `<=`. Off by one here means one request over the free tier every
        single day — which is the request that gets the 429.
        """
        for _ in range(3):
            await burst_rung.note_rung_request()
        assert await burst_rung.rung_requests_today() == 3
        assert await burst_rung.rung_has_budget(4) is True   # 3 used, one left
        assert await burst_rung.rung_has_budget(3) is False  # 3 used, none left

    async def test_zero_disables_the_cap(self, _no_redis):
        for _ in range(50):
            await burst_rung.note_rung_request()
        assert await burst_rung.rung_has_budget(0) is True

    async def test_it_counts_without_redis_rather_than_failing_open(self, _no_redis):
        """
        The whole point of the local tally. If a Redis outage made the count read zero, the
        cap would vanish at exactly the moment the rung is under load.
        """
        await burst_rung.note_rung_request()
        await burst_rung.note_rung_request()
        assert await burst_rung.rung_requests_today() == 2

    async def test_yesterdays_tally_does_not_count_against_today(self, _no_redis, monkeypatch):
        real = burst_rung._today_key
        monkeypatch.setattr(burst_rung, "_today_key", lambda: "ai:rung:requests:2020-01-01")
        for _ in range(10):
            await burst_rung.note_rung_request()
        monkeypatch.setattr(burst_rung, "_today_key", real)
        assert await burst_rung.rung_requests_today() == 0
        assert await burst_rung.rung_has_budget(1) is True
        # And the stale key is not retained — a long-lived process must not grow a dict
        # entry per day it has been running.
        assert len(burst_rung._local_requests) <= 1


class TestItIsWiredIntoTheChain:
    """
    A cap nobody consults is not a cap. `NudgeDeck` was mounted and rendering nothing for
    exactly this reason (docs/MISTAKES.md M11), so the wiring is asserted rather than assumed.
    """

    def test_generate_structured_drops_the_rung_when_the_budget_is_gone(self):
        import inspect

        from app.services.ai import generate

        src = inspect.getsource(generate.generate_structured)
        assert "rung_has_budget" in src, "the daily cap is never consulted"
        assert "is_burst_rung(p) for p in providers" in src, (
            "the cap is checked even when no rung is in the chain — that is a Redis round "
            "trip on the common path"
        )

    def test_a_rung_attempt_is_reserved_before_the_call(self):
        """
        RESERVED, NOT RECORDED ON SUCCESS. Incrementing after a successful call lets a burst of
        concurrent requests all read 1,999 and all proceed. Counting an attempt that then fails
        is the conservative error, and 'must not exceed' is the requirement.
        """
        import inspect

        from app.services.ai import generate

        src = inspect.getsource(generate.generate_structured)
        assert "note_rung_request" in src
        reserve = src.index("note_rung_request")
        call = src.index("ProviderRequest(")
        assert reserve < call, "the reservation happens after the request is built"

    def test_the_setting_exists_and_defaults_to_a_real_number(self):
        from app.core.config import Settings

        f = Settings.model_fields["GROQ_DAILY_REQUEST_LIMIT"]
        assert f.default > 0, "a default of 0 silently disables the cap for every deployment"
