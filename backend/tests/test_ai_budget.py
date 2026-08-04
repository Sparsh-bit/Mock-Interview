"""
Per-user AI metering — tests/test_ai_budget.py

The global $2/day cap was doing duty as a daily allowance, and the consequence was
concrete: one user — or, as it happened, one test run — could spend it and every other
user got the unscored-report fallback until midnight UTC. Splitting it into a per-user
allowance and a much higher circuit breaker fixes that, and these are the properties that
have to hold for the split to mean anything.
"""

from __future__ import annotations

import uuid

import pytest

from app.api.v1.reports import (
    _REASON_PROVIDER,
    _REASON_SERVICE_LIMIT,
    _REASON_TIMEOUT,
    _REASON_USER_QUOTA,
    _classify_failure,
)
from app.core.config import settings
from app.core.exceptions import AIProviderUnavailableError
from app.services.ai import anthropic_provider as ap


class TestTheTwoCapsAreDifferentThings:
    def test_the_global_cap_is_a_breaker_not_an_allowance(self):
        # Its job is stopping a runaway loop, so it must sit well ABOVE a busy day. At
        # $0.23 an interview and $0.14 a GD round, $2 was about nine interviews for the
        # ENTIRE product — which is why it kept tripping in normal use.
        assert settings.AI_DAILY_BUDGET_USD >= 20, (
            "the global cap is low enough to trip on legitimate traffic, which makes it "
            "an allowance rather than a circuit breaker"
        )

    def test_the_per_user_allowance_is_well_below_the_global_breaker(self):
        # If one user could spend the whole global budget, splitting it bought nothing.
        assert 0 < settings.AI_USER_DAILY_BUDGET_USD < settings.AI_DAILY_BUDGET_USD / 10

    def test_the_per_user_allowance_covers_a_real_practice_day(self):
        # A cap so tight that one honest session trips it is worse than no cap: it turns a
        # cost control into a broken product. One interview is ~$0.23, one GD ~$0.14.
        assert settings.AI_USER_DAILY_BUDGET_USD >= 0.40, (
            "should cover at least one full interview plus one GD round"
        )

    def test_the_user_error_is_a_subclass_so_existing_fallback_still_works(self):
        # generate_structured falls through to the free provider on any ProviderError.
        # That is the right behaviour for both caps — the user keeps working — so the new
        # error must not need new handling to avoid becoming a hard failure.
        assert issubclass(ap.UserBudgetExceededError, ap.BudgetExceededError)


def scope() -> str:
    """
    A fresh spend scope per assertion.

    Redis outlives a test run, so reusing a fixed name like "user-A" means a previous run
    — or a manual probe — leaves spend behind and the test fails for a reason that has
    nothing to do with the code. Unique ids keep these independent of Redis state.
    """
    return f"test-{uuid.uuid4()}"


class TestSpendIsScopedPerUser:
    @pytest.mark.asyncio
    async def test_keys_are_separate_per_user_and_per_day(self):
        a, b = scope(), scope()
        assert await ap._spend_key() != await ap._spend_key(a)
        assert await ap._spend_key(a) != await ap._spend_key(b)
        # Both carry the UTC day, so the allowance resets without a cleanup job.
        assert (await ap._spend_key(a)).startswith(await ap._spend_key())

    @pytest.mark.asyncio
    async def test_one_users_spend_does_not_count_against_another(self):
        ap._local_spend.clear()
        spender, bystander = scope(), scope()
        await ap._record_spend(0.50, spender)
        assert await ap._spend_today(spender) >= 0.50
        assert await ap._spend_today(bystander) == 0.0

    @pytest.mark.asyncio
    async def test_recording_one_user_does_not_wipe_the_others(self):
        """
        The bug the day-prefix cleanup exists for.

        The local fallback dict is pruned so it cannot grow forever, and the original rule
        was "delete every key that is not the one being written". With one key per user
        that would delete every OTHER user's tally on every single call, so no per-user
        allowance could ever accumulate — and only when Redis was unavailable, which is
        exactly when the local fallback is the only thing enforcing the cap.
        """
        ap._local_spend.clear()
        users = [scope() for _ in range(3)]
        for user in users:
            await ap._record_spend(0.10, user)
        for user in users:
            assert ap._local_spend.get(await ap._spend_key(user)) == pytest.approx(0.10), (
                f"{user}'s local tally was wiped by a later user's spend"
            )

    @pytest.mark.asyncio
    async def test_a_stale_day_is_pruned(self):
        ap._local_spend.clear()
        ap._local_spend["ai:spend:1999-01-01:whoever"] = 5.0
        await ap._record_spend(0.10, scope())
        assert "ai:spend:1999-01-01:whoever" not in ap._local_spend

    @pytest.mark.asyncio
    async def test_unattributed_spend_counts_only_against_the_global_breaker(self):
        # A background task or a script has no authenticated user. Attributing its spend
        # to an arbitrary user would be worse than not attributing it.
        assert ap._current_user_scope() is None


class TestTheCandidateIsToldTheTruth:
    """
    Four failures used to produce one sentence — "temporarily unavailable, retry shortly".
    For a user who has spent their allowance that sentence is wrong AND sends them into a
    retry loop that cannot succeed until the day rolls over.
    """

    def test_a_personal_allowance_is_not_reported_as_an_outage(self):
        # The ordering trap: UserBudgetExceededError SUBCLASSES BudgetExceededError, so
        # testing the base class first would report every personal limit as a service-wide
        # failure — alarming, and wrong.
        exc = ap.UserBudgetExceededError("used up", provider="anthropic")
        assert _classify_failure(exc) == _REASON_USER_QUOTA

    def test_the_global_breaker_is_reported_as_a_service_limit(self):
        exc = ap.BudgetExceededError("breaker tripped", provider="anthropic")
        assert _classify_failure(exc) == _REASON_SERVICE_LIMIT

    def test_the_reason_is_found_through_a_wrapping_error(self):
        # generate_structured raises AIProviderUnavailableError after exhausting the chain,
        # so the budget error is only ever seen as a cause. Classifying the wrapper alone
        # would lose the distinction entirely.
        inner = ap.UserBudgetExceededError("used up", provider="anthropic")
        outer = AIProviderUnavailableError("all providers failed")
        outer.__cause__ = inner
        assert _classify_failure(outer) == _REASON_USER_QUOTA

    def test_a_timeout_is_its_own_reason(self):
        assert _classify_failure(TimeoutError()) == _REASON_TIMEOUT

    def test_anything_else_is_the_generic_provider_reason(self):
        assert _classify_failure(RuntimeError("boom")) == _REASON_PROVIDER

    def test_classification_terminates_on_a_self_referencing_cause(self):
        # Exception chains can loop; walking one naively hangs the request that was
        # already failing.
        exc = RuntimeError("loop")
        exc.__cause__ = exc
        assert _classify_failure(exc) == _REASON_PROVIDER
