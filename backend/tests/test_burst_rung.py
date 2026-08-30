"""
The free-tier burst rung — tests/test_burst_rung.py

A third provider behind Anthropic and GLM, on a free tier, for the handful of calls where
being served by a weaker model is better than not being served at all.

TWO GATES, BOTH REQUIRED, AND THE SECOND IS THE ONE THAT MATTERS. The cost tier says the
call is not worth reasoning; the feature allowlist says the call is not worth ACCURACY. Those
are different claims, and only the second keeps scoring off a free model — `gd_evaluation`
and `communication_evaluation` are both CHEAP, and both decide a candidate's marks.

The rung must also never be load-bearing: with its key missing, absent, or invalid, the chain
has to behave exactly as it did before it existed.
"""

from __future__ import annotations

import pytest

from app.services.ai.base_provider import CostTier
from app.services.ai.burst_rung import (
    BURST_RUNG_FEATURES,
    eligible_providers,
    is_burst_rung,
)


class _FakeProvider:
    def __init__(self, name: str) -> None:
        self.provider_name = name
        self.model_name = f"{name}-model"


ANTHROPIC = _FakeProvider("anthropic")
GLM = _FakeProvider("glm")
GROQ = _FakeProvider("groq")
FULL_CHAIN = [ANTHROPIC, GLM, GROQ]


def _names(providers) -> list[str]:
    return [p.provider_name for p in providers]


# ─── The allowlist ────────────────────────────────────────────────────────────


class TestWhatMayReachTheFreeTier:
    @pytest.mark.parametrize("feature", ["gd_panel_turn", "interview_panel_turn"])
    def test_a_panel_dialogue_reaction_at_the_cheap_tier_may(self, feature):
        """
        The panel's spoken turns. api/v1/panel.py says it plainly — "The panel is
        presentation" — and the candidate keeps the bare question if it fails, so a weaker
        model costs some flavour and nothing else.
        """
        assert _names(
            eligible_providers(FULL_CHAIN, feature=feature, cost_tier=CostTier.CHEAP)
        ) == ["anthropic", "glm", "groq"]

    @pytest.mark.parametrize(
        "feature",
        [
            "report_generation",
            "report_analysis",
            "cross_question",
            "communication_cross_question",
            "model_answer",
            "gd_evaluation",
            "communication_evaluation",
            "interview_plan",
            "question_generation",
            "question_bank",
            "quiz_generation",
            "resume_analysis_skills",
            "resume_analysis_projects",
            "code_analysis",
            "panel_code_review",
            "gd_topic_prep",
            "study_resources",
        ],
    )
    def test_everything_else_may_not_even_at_the_cheap_tier(self, feature):
        """
        The list is every other `context=` string in the application, enumerated rather than
        sampled — an allowlist is only worth having if adding a feature does not silently
        opt it in. `gd_evaluation` and `communication_evaluation` are the pointed cases:
        both are CHEAP, and both put a number on a candidate.
        """
        assert _names(
            eligible_providers(FULL_CHAIN, feature=feature, cost_tier=CostTier.CHEAP)
        ) == ["anthropic", "glm"]

    @pytest.mark.parametrize("tier", [CostTier.BALANCED, CostTier.DEEP])
    def test_an_allowlisted_feature_asking_for_reasoning_may_not(self, tier):
        """
        Both gates, not either. A call that asks for reasoning is telling us the answer
        matters, whatever its feature name says.
        """
        assert _names(
            eligible_providers(FULL_CHAIN, feature="gd_panel_turn", cost_tier=tier)
        ) == ["anthropic", "glm"]

    def test_an_unrecognised_feature_may_not(self):
        """Default deny. A new call site is off the free tier until somebody adds it."""
        assert _names(
            eligible_providers(FULL_CHAIN, feature="something_new", cost_tier=CostTier.CHEAP)
        ) == ["anthropic", "glm"]

    def test_the_allowlist_contains_nothing_that_scores_or_generates_assessed_content(self):
        """
        A guard on the allowlist itself, so growing it stays a deliberate act. Anything that
        evaluates, reports, questions or produces a model answer is barred by name.
        """
        banned = ("evaluation", "report", "cross_question", "model_answer", "analysis",
                  "plan", "question", "quiz", "code")
        for feature in BURST_RUNG_FEATURES:
            assert not any(word in feature for word in banned), (
                f"{feature!r} is on the burst-rung allowlist but its name says it scores or "
                f"generates assessed content"
            )


# ─── Ordering ─────────────────────────────────────────────────────────────────


class TestItIsStrictlyLast:
    def test_the_burst_rung_never_moves_ahead_of_a_paid_provider(self):
        order = _names(
            eligible_providers(FULL_CHAIN, feature="gd_panel_turn", cost_tier=CostTier.CHEAP)
        )
        assert order.index("groq") == len(order) - 1

    def test_filtering_preserves_the_order_of_the_providers_it_keeps(self):
        chain = [GLM, ANTHROPIC, GROQ]
        assert _names(
            eligible_providers(chain, feature="report_generation", cost_tier=CostTier.DEEP)
        ) == ["glm", "anthropic"]

    def test_a_chain_without_a_burst_rung_is_returned_untouched(self):
        chain = [ANTHROPIC, GLM]
        assert eligible_providers(
            chain, feature="gd_panel_turn", cost_tier=CostTier.CHEAP
        ) == chain

    def test_is_burst_rung_identifies_only_the_free_tier_providers(self):
        assert is_burst_rung(GROQ) is True
        assert is_burst_rung(ANTHROPIC) is False
        assert is_burst_rung(GLM) is False


# ─── It must never be load-bearing ────────────────────────────────────────────


class TestTheChainWithoutIt:
    def test_the_chain_builds_normally_when_the_burst_key_is_absent(self, monkeypatch):
        """
        The headline requirement. No key, no rung, no error, no change to anything else.
        """
        from app.core.config import settings
        from app.services.ai import provider_factory

        monkeypatch.setattr(settings, "AI_PROVIDER", "glm")
        monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "nvidia")
        monkeypatch.setattr(settings, "AI_BURST_PROVIDER", "groq")
        monkeypatch.setattr(settings, "GROQ_API_KEY", "")

        chain = provider_factory._build_provider_chain()

        assert _names(chain) == ["glm", "nvidia"]

    def test_the_chain_builds_normally_when_no_burst_provider_is_configured(self, monkeypatch):
        from app.core.config import settings
        from app.services.ai import provider_factory

        monkeypatch.setattr(settings, "AI_PROVIDER", "glm")
        monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "nvidia")
        monkeypatch.setattr(settings, "AI_BURST_PROVIDER", "")

        assert _names(provider_factory._build_provider_chain()) == ["glm", "nvidia"]

    def test_the_burst_rung_is_appended_after_the_paid_chain_when_it_is_configured(
        self, monkeypatch
    ):
        from app.core.config import settings
        from app.services.ai import provider_factory

        monkeypatch.setattr(settings, "AI_PROVIDER", "glm")
        monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "nvidia")
        monkeypatch.setattr(settings, "AI_BURST_PROVIDER", "groq")
        monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test_key")

        assert _names(provider_factory._build_provider_chain()) == ["glm", "nvidia", "groq"]

    def test_a_chain_of_only_the_burst_rung_is_refused(self, monkeypatch):
        """
        THE ONE THAT WOULD BOOT LOOKING FINE. If both paid providers fail to construct and
        the free one succeeds, the chain is not empty — so the existing "nothing to run on"
        guard would pass, the service would start, and then every report, every score and
        every cross-question would fail, because the allowlist correctly refuses to serve
        them from a free tier. A rung that cannot carry the product must not be allowed to
        look like one that can.
        """
        from app.core.config import settings
        from app.services.ai import provider_factory

        monkeypatch.setattr(settings, "AI_PROVIDER", "glm")
        monkeypatch.setattr(settings, "GLM_API_KEY", "")
        monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "nvidia")
        monkeypatch.setattr(settings, "NVIDIA_API_KEY", "")
        monkeypatch.setattr(settings, "AI_BURST_PROVIDER", "groq")
        monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test_key")

        with pytest.raises(RuntimeError) as raised:
            provider_factory._build_provider_chain()

        # The message has to name the actual problem. "No AI provider could be created" is
        # not it — one was — and sending somebody to look for a missing key without saying
        # which two are missing wastes the outage.
        message = str(raised.value)
        assert "burst rung" in message
        assert "cannot serve" in message
        assert "'glm'" in message and "'nvidia'" in message

    def test_an_invalid_burst_key_is_a_call_time_failure_the_chain_already_handles(
        self, monkeypatch
    ):
        """
        A wrong key is indistinguishable from a right one until a call is made — nothing can
        validate it at construction. What matters is that it is LAST, so the paid providers
        have already had their turn and a 401 from the free tier changes nothing.
        """
        from app.core.config import settings
        from app.services.ai import provider_factory

        monkeypatch.setattr(settings, "AI_PROVIDER", "glm")
        monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "")
        monkeypatch.setattr(settings, "AI_BURST_PROVIDER", "groq")
        monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_definitely_not_valid")

        chain = provider_factory._build_provider_chain()
        assert _names(chain)[-1] == "groq"
        assert _names(chain)[0] == "glm"


class TestItIsWiredIntoTheGenerationPath:
    def test_generate_structured_filters_the_chain_through_the_allowlist(self):
        """
        The policy is worthless if nothing consults it. Asserted against the source rather
        than by making a real AI call, which is the only honest option without a network.
        """
        import inspect

        from app.services.ai import generate

        source = inspect.getsource(generate.generate_structured)
        assert "eligible_providers" in source, (
            "generate_structured does not filter the provider chain — the burst rung would "
            "be reachable from every feature"
        )


class TestTheSettings:
    def test_the_burst_provider_is_off_by_default(self):
        from app.core.config import Settings

        assert Settings.model_fields["AI_BURST_PROVIDER"].default == ""

    @pytest.mark.parametrize("name", ["GROQ_API_KEY", "GROQ_MODEL", "GROQ_BASE_URL"])
    def test_the_groq_settings_exist(self, name):
        from app.core.config import Settings

        assert name in Settings.model_fields

    def test_the_groq_key_defaults_to_empty_so_the_rung_is_absent_unless_configured(self):
        from app.core.config import Settings

        assert Settings.model_fields["GROQ_API_KEY"].default == ""
