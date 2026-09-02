"""
The free-tier cap must match the model it is capping — tests/test_groq_limit_matches_model.py

THE INCONSISTENCY. `GROQ_MODEL` defaults to `openai/gpt-oss-20b`, and both
services/ai/burst_rung.py and GROQ_DAILY_REQUEST_LIMIT's own description record that model's
free allowance as 1,000 requests a day (verified 2026-08-30). The limit defaulted to 2,000.

So the out-of-the-box pair was a cap set to twice the ceiling it was capping. The cap would
never fire; the rung would keep calling until Groq answered 429 — which is precisely the
outcome the field exists to avoid, and its description says so: "it fails after a round trip
and leaves the account rate-limited, which the next health check reports as a provider
outage." A cap that cannot fire is worse than no cap, because it reads as protection.

The description already told the operator to set this per model. That is right, and it stays -
these limits are per-model and they change. But a DEFAULT that contradicts the neighbouring
default is a trap for anyone who turns the rung on without reading both fields, and the whole
point of the rung is that it is reached during an outage, when nobody is reading anything.
"""

from __future__ import annotations

from app.core.config import Settings


class TestTheDefaultsAgreeWithEachOther:
    def test_the_daily_limit_matches_the_default_model_allowance(self):
        """
        1,000/day is the verified figure for openai/gpt-oss-20b, which is GROQ_MODEL's default.
        If GROQ_MODEL's default ever changes, this should fail and be re-derived - not raised.
        """
        assert Settings.model_fields["GROQ_MODEL"].default == "openai/gpt-oss-20b"
        assert Settings.model_fields["GROQ_DAILY_REQUEST_LIMIT"].default == 1000

    def test_the_cap_can_actually_fire(self):
        """
        THE PROPERTY THAT MATTERS, stated independently of the number: a cap above the
        provider's own ceiling is decoration. Whatever the two defaults become, the limit must
        not exceed the allowance the description records for that model.
        """
        limit = Settings.model_fields["GROQ_DAILY_REQUEST_LIMIT"].default
        described = Settings.model_fields["GROQ_DAILY_REQUEST_LIMIT"].description or ""
        assert "1,000/day" in described, "the verified allowance is no longer documented here"
        assert limit <= 1000

    def test_zero_still_disables_it(self):
        """
        THE VACUITY GUARD. Tightening a default must not remove the off switch - 0 means "no
        cap", and burst_rung.has_budget treats a non-positive limit as unlimited.
        """
        import asyncio

        from app.db import daily_counter

        async def check() -> bool:
            return await daily_counter.has_budget("ai:rung", 0)

        assert asyncio.run(check()) is True
