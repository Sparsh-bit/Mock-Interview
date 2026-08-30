"""
Routing a cheap call to a cheap model — tests/test_model_routing.py

`CostTier.CHEAP` meant "not worth paying to REASON about" — no thinking, low effort — and
never meant a different MODEL. Every tier resolved to the same one, so the price sheet's
entry for `claude-haiku-4-5` was priced, tested and never selected by anything.

It can be selected now. Whether it SHOULD be is a separate question, and the measurement
answered it "not yet": see docs/AI-COST-MODEL.md and the note at the top of
services/ai/model_routing.py. So the routing ships switched off, and these tests are mostly
about the ways it could hurt somebody if it were switched on carelessly.

THE FOUR THINGS THAT WOULD GO WRONG, each tested below:

  1. ROUTING A CALL THAT SCORES SOMEBODY. Four of the six CHEAP call sites are not dialogue:
     two grade a candidate and two write into a cache shared with every other candidate on
     the track. A cost tier alone cannot tell those apart from a panel turn — they are all
     CHEAP — which is exactly why the gate is feature AND tier.

  2. SENDING A MODEL PARAMETERS IT REJECTS. Measured against the live API: Haiku 4.5 returns
     400 for `output_config.effort` and for adaptive thinking. This was not theoretical —
     the first run of the comparison harness failed 9 times out of 9 on it. And the failure
     would have been nearly invisible in production: a panel turn that 400s produces no
     turns, the caller falls back to the bare question, and the interview continues looking
     slightly flat. That symptom already cost this repo a four-round investigation.

  3. THE OFF SWITCH NOT WORKING. An empty ANTHROPIC_CHEAP_MODEL must send everything to the
     configured model. It is the one thing somebody will reach for at speed if a smaller
     model turns out to be wrong in production.

  4. THE DEFAULT DRIFTING ON. Turning this on accepts a measured quality regression for a
     real saving. That is a decision, and a decision is not a default.
"""

from __future__ import annotations

import pytest

from app.services.ai.anthropic_provider import (
    _DEFAULT_CAPABILITIES,
    _MODEL_CAPABILITIES,
    AnthropicProvider,
)
from app.services.ai.base_provider import CostTier, ProviderMessage, ProviderRequest
from app.services.ai.model_routing import (
    CHEAP_MODEL_FEATURES,
    wants_cheap_model,
)

SONNET = "claude-sonnet-5"
HAIKU = "claude-haiku-4-5"

#: Every context= label that passes CostTier.CHEAP today, from the six call sites.
_ALL_CHEAP_CALL_SITES = (
    "gd_panel_turn",
    "interview_panel_turn",
    "gd_evaluation",
    "communication_evaluation",
    "question_bank",
    "study_resources",
)


def _request(feature, tier=CostTier.CHEAP, max_tokens=320):
    return ProviderRequest(
        messages=[ProviderMessage(role="user", content="hi")],
        max_tokens=max_tokens,
        cost_tier=tier,
        feature=feature,
    )


def _provider(cheap=HAIKU, model=SONNET):
    return AnthropicProvider(
        api_key="k", model=model, cheap_model=cheap, daily_budget_usd=0.0
    )


class TestOnlyDialogueIsRouted:
    @pytest.mark.parametrize("feature", sorted(CHEAP_MODEL_FEATURES))
    def test_panel_dialogue_may_use_the_cheap_model(self, feature):
        assert wants_cheap_model(feature=feature, cost_tier=CostTier.CHEAP) is True
        assert _provider()._select_model(_request(feature)) == HAIKU

    @pytest.mark.parametrize(
        "feature",
        [f for f in _ALL_CHEAP_CALL_SITES if f not in {"gd_panel_turn", "interview_panel_turn"}],
    )
    def test_a_cheap_call_that_is_not_dialogue_stays_on_the_configured_model(self, feature):
        """
        THE POINT OF THE FEATURE GATE, and the reason a cost tier alone would not do.

        `gd_evaluation` and `communication_evaluation` GRADE a candidate; a model that marks
        half a point more generously produces a report that is wrong in a direction nobody
        can see, on the thing the candidate came for. `question_bank` and `study_resources`
        write into caches served to every other candidate on the track, so one weak batch
        outlives the session that caused it.

        All four are CostTier.CHEAP. Nothing about the tier distinguishes them from a panel
        turn.
        """
        assert wants_cheap_model(feature=feature, cost_tier=CostTier.CHEAP) is False
        assert _provider()._select_model(_request(feature)) == SONNET

    @pytest.mark.parametrize("tier", [CostTier.BALANCED, CostTier.DEEP])
    def test_a_dialogue_feature_raised_above_cheap_is_not_routed(self, tier):
        # A call site asking for more reasoning is saying the answer matters, whatever its
        # feature name is on the allowlist.
        assert wants_cheap_model(feature="interview_panel_turn", cost_tier=tier) is False
        assert _provider()._select_model(_request("interview_panel_turn", tier)) == SONNET

    def test_a_call_that_declares_no_feature_is_never_routed(self):
        # `feature` is None for anything not going through generate_structured. An unnamed
        # call cannot be on an allowlist, and defaulting to the configured model is the
        # direction where being wrong costs money rather than quality.
        assert wants_cheap_model(feature=None, cost_tier=CostTier.CHEAP) is False
        assert wants_cheap_model(feature="", cost_tier=CostTier.CHEAP) is False
        assert _provider()._select_model(_request(None)) == SONNET

    def test_the_allowlist_is_a_subset_of_the_real_cheap_call_sites(self):
        # A name here that no call site passes routes nothing and hides a typo — the gate
        # would silently never fire and the saving would never appear.
        assert set(_ALL_CHEAP_CALL_SITES) >= CHEAP_MODEL_FEATURES


class TestTheOffSwitch:
    def test_an_empty_cheap_model_routes_nothing(self):
        """
        The one thing somebody reaches for at speed if a smaller model turns out to be wrong
        in production. It must need no code change, no allowlist edit and no deploy — one
        environment value, and every call is back on the configured model.
        """
        off = _provider(cheap="")
        for feature in _ALL_CHEAP_CALL_SITES:
            assert off._select_model(_request(feature)) == SONNET

    def test_whitespace_is_not_a_model_name(self):
        # This arrives from a hosting provider's environment UI, where a value can end up
        # as a space. A model called " " would 400 every panel turn.
        assert _provider(cheap="   ")._select_model(_request("gd_panel_turn")) == SONNET

    def test_an_explicit_model_override_still_wins(self):
        """
        The per-request escape hatch predates this and must keep working — it is what the
        comparison harness used to drive both models through one provider.

        THE TWO LAYERS ARE SEPARATE ON PURPOSE. `_select_model` answers "what does policy
        say for this call?" and knows nothing about overrides; `_build_payload` gives an
        explicit override precedence over that answer. Folding the override into the policy
        would make the policy untestable in isolation, which is most of what the class above
        does.
        """
        req = _request("gd_panel_turn").model_copy(
            update={"model_override": "claude-opus-5"}
        )
        # Policy on its own still says this call is routable — the override is not its job.
        assert _provider()._select_model(req) == HAIKU
        # And the payload the vendor actually receives honours the override.
        _payload, model, *_ = _provider()._build_payload(req)
        assert model == "claude-opus-5"


class TestTheModelIsSentOnlyWhatItAccepts:
    """
    MEASURED AGAINST THE LIVE API, NOT ASSUMED, and the first version of this routing was
    broken by it: 9 out of 9 comparison calls returned

        400 invalid_request_error: This model does not support the effort parameter

    A panel turn that 400s produces no turns, the caller falls back to putting the bare
    question, and the interview carries on looking slightly flat. Nothing tells the
    candidate, and the log line for it is one warning among many — the same shape of silent
    failure that already cost this repo a four-round investigation into the wrong layer.
    """

    def test_haiku_is_recorded_as_supporting_neither(self):
        assert _MODEL_CAPABILITIES[HAIKU] == (False, False)

    def test_an_unlisted_model_is_assumed_to_support_both(self):
        # The safe direction for a model added later: being wrong this way is one loud 400
        # on a new model, while assuming False would silently stop buying reasoning on a
        # DEEP call and nothing would say so.
        assert _DEFAULT_CAPABILITIES == (True, True)
        payload, *_ = _provider()._build_payload(_request("interview_panel_turn"))
        assert payload["model"] == HAIKU

    def test_no_effort_field_is_sent_to_a_model_that_rejects_it(self):
        payload, model, *_ = _provider()._build_payload(_request("interview_panel_turn"))
        assert model == HAIKU
        assert "output_config" not in payload

    def test_the_effort_field_is_still_sent_to_a_model_that_takes_it(self):
        # The saving must not be bought by quietly dropping a cost control everywhere else.
        # `effort` caps overall token spend on Sonnet and has to keep doing so.
        payload, model, *_ = _provider()._build_payload(_request("gd_evaluation"))
        assert model == SONNET
        assert payload["output_config"] == {"effort": "low"}

    def test_thinking_is_still_stated_explicitly_on_the_cheap_model(self):
        # Omitting `thinking` is what silently buys adaptive reasoning on Sonnet 5, so it is
        # always explicit. Haiku accepts `disabled` — verified live — it only rejects
        # `adaptive`, so nothing is lost by keeping the field.
        payload, *_ = _provider()._build_payload(_request("interview_panel_turn"))
        assert payload["thinking"] == {"type": "disabled"}

    def test_a_model_without_adaptive_thinking_degrades_rather_than_400s(self):
        """
        Unreachable through the allowlist today — DEEP is never routed — and tested anyway.

        It is reachable by configuration: ANTHROPIC_MODEL itself could be set to a model
        with no adaptive thinking, and then every DEEP call would 400. Answering without
        reasoning is the only option that produces an answer at all; the provider logs a
        warning so it cannot be mistaken for the reasoning having happened.
        """
        provider = AnthropicProvider(
            api_key="k", model=HAIKU, cheap_model="", daily_budget_usd=0.0
        )
        payload, model, _max, thinking_enabled, _effort = provider._build_payload(
            _request("report_generation", CostTier.DEEP, max_tokens=8000)
        )
        assert model == HAIKU
        assert thinking_enabled is False
        assert payload["thinking"] == {"type": "disabled"}
        assert "output_config" not in payload

    def test_a_deep_call_on_a_capable_model_still_buys_reasoning(self):
        # The guard above must not have quietly disabled thinking for everybody.
        provider = AnthropicProvider(
            api_key="k", model=SONNET, cheap_model="", daily_budget_usd=0.0
        )
        payload, _model, _max, thinking_enabled, _effort = provider._build_payload(
            _request("report_generation", CostTier.DEEP, max_tokens=8000)
        )
        assert thinking_enabled is True
        assert payload["thinking"] == {"type": "adaptive"}


class TestTheFeatureReachesTheProvider:
    def test_generate_structured_passes_its_context_down_as_the_feature(self):
        """
        Without this the policy has nothing to key on and every call looks unnamed — the
        routing would be inert and the saving would silently never appear.

        The SAME `context` the ledger and the burst rung already use, passed rather than
        re-derived, so the three cannot come to disagree about what a call is.
        """
        import inspect

        from app.services.ai import generate

        src = inspect.getsource(generate.generate_structured)
        assert "feature=context," in src

    def test_the_request_model_carries_it(self):
        assert "feature" in ProviderRequest.model_fields
        assert ProviderRequest.model_fields["feature"].default is None


class TestTurningItOnIsADecisionNotADefault:
    def test_the_cheap_model_is_unset_by_default(self):
        """
        THE MEASUREMENT IS WHY, and it is worth restating where somebody changing this will
        read it. Nine realistic panel moments, both models, identical inputs, run twice:

          Haiku    60-70% cheaper, same latency, 9/9 parseable, no invented speakers, and
                   BETTER than Sonnet at the `asked_question` flag.
          And      SIX lines over the prompt's own twenty-five-word limit out of ~21, in
                   BOTH runs — longest 46 words, then 41 — where Sonnet produced ZERO in
                   both. One turn used the candidate's name after being told in capitals not
                   to. On a wrong answer it explained the concept instead of asking the
                   follow-up, which is the exact lecturing interview_panel.md was rewritten
                   to stop.

        Switching it on trades a measured regression for a real saving. Somebody may well
        decide that is worth it. Nobody should decide it by not noticing a default.
        """
        from app.core.config import Settings

        assert Settings.model_fields["ANTHROPIC_CHEAP_MODEL"].default == ""

    def test_the_configured_model_default_is_unchanged(self):
        # BALANCED and DEEP were not part of this change and must not have moved.
        from app.core.config import Settings

        assert Settings.model_fields["ANTHROPIC_MODEL"].default == SONNET

    def test_the_price_sheet_knows_the_cheap_model(self):
        # Routing to a model the cost estimator has never heard of would silently bill it at
        # the default (Sonnet) rate, which would make the saving invisible in `ai_usage` —
        # the one place anybody would go to check whether it worked.
        from app.services.ai.anthropic_provider import _PRICE_PER_MTOK

        assert HAIKU in _PRICE_PER_MTOK
        haiku_in, haiku_out = _PRICE_PER_MTOK[HAIKU]
        sonnet_in, sonnet_out = _PRICE_PER_MTOK[SONNET]
        assert haiku_in < sonnet_in and haiku_out < sonnet_out
