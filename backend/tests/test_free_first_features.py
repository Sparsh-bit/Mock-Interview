"""
Some features try the free provider FIRST — tests/test_free_first_features.py

WHAT WAS MISSING. `burst_rung.py` already decides which calls may reach a model we do not pay
for, but only as a LAST RESORT: the rung sits behind both paid providers and is reached when
they have already failed. There was no way to say "this feature should PREFER the free
provider", so every quiz question was bought from Anthropic even though a quiz is exactly the
kind of work a small model does adequately.

WHY REORDERING THE CHAIN RATHER THAN A NEW PARAMETER. `generate_structured` already walks the
provider list in order and falls through on failure, with retries, backoff, validation and
usage accounting applied per provider. Putting the free provider FIRST for an allowlisted
feature reuses all of that and adds no new failure mode: if Groq is throttled, refuses, or
returns something that will not validate, the call proceeds to Anthropic exactly as it does
today. A `prefer_provider=` argument would have needed its own fallback logic.

THE GATE IS THE FEATURE, NOT THE COST TIER, and that is deliberate. `quiz_generation` is
BALANCED, not CHEAP — so a tier gate could not have reached it — while `gd_evaluation` and
`communication_evaluation` ARE cheap and must never go first to a free model, because they put
a number on a candidate. burst_rung.py already argues this at length; the same reasoning
applies with more force here, because "first" means it happens on the happy path rather than
only during an outage.

WHAT PROTECTS QUALITY. A quiz question that fails schema validation never reaches a candidate
— `generate_structured` rejects it and moves to the next provider — and `api/v1/quiz.py` falls
through to the curated bank when generation comes up short. So the downside of the free
provider having a bad minute is a quiz served from the bank, which is the designed behaviour.
"""

from __future__ import annotations

from app.services.ai import burst_rung
from app.services.ai.base_provider import CostTier


class _P:
    def __init__(self, name: str):
        self.provider_name = name


ANTHROPIC, GLM, GROQ = _P("anthropic"), _P("glm"), _P("groq")


def _names(providers):
    return [p.provider_name for p in providers]


class TestTheFreeProviderGoesFirstForAllowlistedFeatures:
    def test_quiz_generation_prefers_the_free_provider(self):
        out = burst_rung.prefer_free_first(
            [ANTHROPIC, GLM, GROQ], feature="quiz_generation", cost_tier=CostTier.BALANCED
        )
        assert _names(out)[0] == "groq"

    def test_the_paid_providers_remain_behind_it_in_order(self):
        """
        Preference, not replacement. If the free provider is throttled or returns junk the
        call must still reach Anthropic and then GLM, in that order.
        """
        out = burst_rung.prefer_free_first(
            [ANTHROPIC, GLM, GROQ], feature="quiz_generation", cost_tier=CostTier.BALANCED
        )
        assert _names(out) == ["groq", "anthropic", "glm"]

    def test_a_feature_not_on_the_list_is_untouched(self):
        for feature in ("report_generation", "cross_question", "interview_plan"):
            out = burst_rung.prefer_free_first(
                [ANTHROPIC, GLM, GROQ], feature=feature, cost_tier=CostTier.BALANCED
            )
            assert _names(out) == ["anthropic", "glm", "groq"], feature

    def test_it_is_inert_when_no_free_provider_is_configured(self):
        """
        AI_BURST_PROVIDER empty means the chain has no free rung at all. The reorder must then
        be a no-op rather than an error - that is the default configuration.
        """
        out = burst_rung.prefer_free_first(
            [ANTHROPIC, GLM], feature="quiz_generation", cost_tier=CostTier.BALANCED
        )
        assert _names(out) == ["anthropic", "glm"]


class TestScoringNeverGoesToAFreeModelFirst:
    """
    THE VACUITY GUARD, and the one that matters most. burst_rung.py already refuses to let a
    free model score a candidate even as a last resort. Preferring it FIRST would put that on
    the happy path, which is strictly worse.
    """

    def test_the_evaluations_are_not_on_the_free_first_list(self):
        for feature in ("gd_evaluation", "communication_evaluation", "report_analysis"):
            assert feature not in burst_rung.FREE_FIRST_FEATURES, feature

    def test_nothing_that_writes_a_report_is_on_the_list(self):
        for feature in ("report_generation", "report_analysis"):
            assert feature not in burst_rung.FREE_FIRST_FEATURES, feature

    def test_the_list_is_small_and_explicit(self):
        """
        A growing free-first list is how quality erodes quietly. Anything added here should be
        a deliberate decision with a comment, not a default.
        """
        assert len(burst_rung.FREE_FIRST_FEATURES) <= 3


class TestItIsWiredIntoTheChain:
    def test_generate_structured_applies_the_preference(self):
        """A policy nobody consults protects nothing - docs/MISTAKES.md M11."""
        import inspect

        from app.services.ai import generate

        src = inspect.getsource(generate.generate_structured)
        assert "prefer_free_first" in src
