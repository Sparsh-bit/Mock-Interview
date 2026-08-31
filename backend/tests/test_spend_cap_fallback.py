"""
A spent Anthropic account falls through instead of being retried — tests/test_spend_cap_fallback.py

WHAT THIS IS ABOUT. Anthropic enforces a MONTHLY spend cap on the account, separate from our
own `AI_DAILY_BUDGET_USD`. Past it every call answers 429 with
`error_code: enforced_spend_limit_reached` and NO `retry-after` header — because there is no
time at which the request would succeed. It is 429 by status and permanent by nature.

WHY THAT MATTERS TO THE CHAIN. generate.py already treats two errors as permanent and breaks
to the next provider immediately: a rejected credential, and our own daily budget. Both for the
same reason — "a second attempt is a guaranteed-wasted call and, worse, delay taken from
whatever budget the caller is working inside." A spend-cap 429 is the third case and was
being handled as the OPPOSITE: `is_rate_limit()` is true, so it earned the two-second
rate-limit backoff and a second doomed attempt before the fallback was reached.

The cost is paid where it hurts most. A panel turn has a 12s budget and a report 85s; four
wasted seconds inside a 12s budget is a third of it, spent waiting for an answer that cannot
arrive, at the exact moment the fallback provider is the only thing that can still answer.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.services.ai.base_provider import CostTier, ProviderError, ProviderResponse


class _Answer(BaseModel):
    ok: bool


_SPEND_CAP_BODY = (
    '{"type":"error","error":{"type":"rate_limit_error",'
    '"message":"This request would exceed your organization\'s monthly spend limit.",'
    '"error_code":"enforced_spend_limit_reached"}}'
)


class _FakeProvider:
    """Records how many times it was called, so a wasted retry is visible."""

    supports_streaming = False

    def __init__(self, name: str, *, raises: Exception | None = None):
        self.provider_name = name
        self._raises = raises
        self.calls = 0

    async def complete(self, request):  # noqa: ANN001 - test double
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return ProviderResponse(
            content='{"ok": true}',
            model=f"{self.provider_name}-model",
            prompt_tokens=10,
            completion_tokens=5,
            finish_reason="stop",
            estimated_cost_usd=0.0,
        )


class TestTheSpendCapIsToldApartFromARateLimit:
    """
    Both are 429. Only one of them can be fixed by waiting, and the whole behaviour below
    hangs on the distinction.
    """

    def test_a_spend_cap_429_is_recognised(self):
        exc = ProviderError(
            f"anthropic API returned 429: {_SPEND_CAP_BODY}",
            provider="anthropic",
            status_code=429,
        )
        assert exc.is_spend_cap() is True

    def test_an_ordinary_rate_limit_is_not_a_spend_cap(self):
        """
        THE VACUITY GUARD. An `is_spend_cap` that returned True for every 429 would satisfy
        the test above and would stop the chain retrying real rate limits — the one error
        where waiting IS the entire fix.
        """
        exc = ProviderError(
            'anthropic API returned 429: {"error":{"type":"rate_limit_error",'
            '"message":"Number of request tokens has exceeded your per-minute rate limit"}}',
            provider="anthropic",
            status_code=429,
        )
        assert exc.is_spend_cap() is False

    def test_a_non_429_carrying_the_phrase_is_not_a_spend_cap(self):
        """Status and body must agree, or a 500 whose body quotes the error text misroutes."""
        exc = ProviderError(
            f"anthropic API returned 500: {_SPEND_CAP_BODY}",
            provider="anthropic",
            status_code=500,
        )
        assert exc.is_spend_cap() is False


@pytest.mark.asyncio
class TestTheChainDoesNotRetryASpentAccount:
    async def test_the_primary_is_tried_once_then_the_fallback_answers(self, monkeypatch):
        """
        The behaviour that matters: ONE call to the spent provider, not two, and a real
        answer from the fallback.
        """
        from app.services.ai import generate as gen

        primary = _FakeProvider(
            "anthropic",
            raises=ProviderError(
                f"anthropic API returned 429: {_SPEND_CAP_BODY}",
                provider="anthropic",
                status_code=429,
            ),
        )
        fallback = _FakeProvider("glm")
        monkeypatch.setattr(gen, "get_ai_providers", lambda: [primary, fallback])

        parsed, _ = await gen.generate_structured(
            _Answer,
            [],
            max_tokens=64,
            attempts_per_provider=2,
            cost_tier=CostTier.CHEAP,
            context="test_spend_cap",
        )

        assert parsed.ok is True
        assert primary.calls == 1, "a spent account was retried — the 429 is permanent"
        assert fallback.calls == 1

    async def test_it_does_not_pay_the_rate_limit_backoff(self, monkeypatch):
        """
        Breaking out is only half the win. The two-second rate-limit sleep must not be spent
        either — inside a 12s panel-turn budget that sleep is a sixth of the whole thing.
        """
        from app.services.ai import generate as gen

        slept: list[float] = []

        async def _record_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(gen.asyncio, "sleep", _record_sleep)

        primary = _FakeProvider(
            "anthropic",
            raises=ProviderError(
                f"anthropic API returned 429: {_SPEND_CAP_BODY}",
                provider="anthropic",
                status_code=429,
            ),
        )
        fallback = _FakeProvider("glm")
        monkeypatch.setattr(gen, "get_ai_providers", lambda: [primary, fallback])

        await gen.generate_structured(
            _Answer, [], max_tokens=64, attempts_per_provider=2, context="test_spend_cap"
        )

        assert slept == [], f"waited {slept}s for a limit that time cannot clear"

    async def test_an_ordinary_rate_limit_still_gets_its_retry_and_its_backoff(
        self, monkeypatch
    ):
        """
        THE VACUITY GUARD for the chain. If the new branch caught every 429, real rate limits
        would lose the retry-with-backoff that production log was fixed to add.
        """
        from app.services.ai import generate as gen

        slept: list[float] = []

        async def _record_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(gen.asyncio, "sleep", _record_sleep)

        primary = _FakeProvider(
            "anthropic",
            raises=ProviderError(
                'anthropic API returned 429: {"error":{"message":"per-minute rate limit"}}',
                provider="anthropic",
                status_code=429,
            ),
        )
        fallback = _FakeProvider("glm")
        monkeypatch.setattr(gen, "get_ai_providers", lambda: [primary, fallback])

        await gen.generate_structured(
            _Answer, [], max_tokens=64, attempts_per_provider=2, context="test_rate_limit"
        )

        assert primary.calls == 2, "a real rate limit lost its retry"
        assert slept == [gen._RATE_LIMIT_BACKOFF_SECONDS]
