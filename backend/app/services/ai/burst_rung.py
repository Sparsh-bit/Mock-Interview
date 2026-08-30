"""
The free-tier burst rung — services/ai/burst_rung.py

WHAT MAY BE ANSWERED BY A MODEL WE DO NOT PAY FOR. One policy, in one place, consulted by
generate_structured before it walks the provider chain.

The rung sits strictly behind the paid providers and is reached only when both of them have
already failed — a daily spend cap, a rate limit, an outage. In that window, some calls are
better served by a weaker model than not served at all, and some are not. This module is the
line between them.

TWO GATES, BOTH REQUIRED, AND THE SECOND IS THE ONE THAT DOES THE WORK.

    CostTier.CHEAP  says the call is not worth paying to REASON about.
    the allowlist   says the call is not worth being RIGHT about.

Those are different claims, and only the second keeps scoring off a free model. Both
`gd_evaluation` and `communication_evaluation` are CHEAP — the rubric is in the prompt, so
there is nothing to deliberate — and both put a number on a candidate. A tier gate alone
would hand a candidate's marks to whatever the free tier happened to say that minute, which
is exactly the outcome this file exists to prevent.

IT IS NOT CAPACITY. Groq's free plan for openai/gpt-oss-20b is 30 RPM / 1,000 requests a day
/ 8,000 tokens a minute (verified 2026-08-30; these change). A panel turn is ~3.5k tokens, so
that ceiling is roughly TWO turns a minute against the 3.25 a single live GD round produces.
One concurrent round does not fit. The rung catches a blip; it does not carry load, and
sizing anything against it would be a mistake.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base_provider import CostTier

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .base_provider import BaseAIProvider

#: Providers that may only serve allowlisted calls. Named rather than flagged on the class,
#: because OpenAICompatibleProvider is shared with GLM and NVIDIA — the restriction belongs
#: to the ACCOUNT and its free tier, not to the transport.
BURST_RUNG_PROVIDERS = frozenset({"groq"})

#: The `context=` values that may fall through to the burst rung.
#:
#: DEFAULT DENY. A `context` not on this list cannot reach the rung, so a new call site is
#: off the free tier until somebody puts it here on purpose.
#:
#: Both entries are panel dialogue — the interviewers' spoken reactions around a question.
#: They are presentation: api/v1/panel.py says so in as many words, and when the call fails
#: the candidate still gets the bare question, so a weaker model costs some flavour and
#: nothing measurable. Nothing else in the application qualifies:
#:
#:   * report_generation / report_analysis — the product's judgement about a person
#:   * gd_evaluation / communication_evaluation — scoring, despite being CHEAP
#:   * cross_question / model_answer / question_bank — content a candidate is assessed on
#:   * resume_analysis_* / code_analysis / panel_code_review — read a candidate's own work
#:
#: THE BRIEF ALSO NAMED "classification checks", AND THERE ARE NONE TODAY. No call site in
#: this application does a classification; the nearest things are evaluations, and those
#: score. The category is left described rather than filled, so that whoever adds the first
#: real classifier knows it belongs here and does not have to re-derive the rule.
BURST_RUNG_FEATURES = frozenset(
    {
        "gd_panel_turn",
        "interview_panel_turn",
    }
)

#: The only tier that may fall through. Anything asking for more reasoning is telling us the
#: answer matters, whatever its feature name claims.
BURST_RUNG_COST_TIER = CostTier.CHEAP


def is_burst_rung(provider: BaseAIProvider) -> bool:
    """True when this provider may only serve allowlisted calls."""
    return provider.provider_name in BURST_RUNG_PROVIDERS


def burst_rung_allows(*, feature: str, cost_tier: CostTier) -> bool:
    """Both gates. Neither is sufficient alone — see the module docstring."""
    return cost_tier == BURST_RUNG_COST_TIER and feature in BURST_RUNG_FEATURES


def eligible_providers(
    providers: Sequence[BaseAIProvider],
    *,
    feature: str,
    cost_tier: CostTier,
) -> list[BaseAIProvider]:
    """
    The chain this particular call is allowed to walk.

    Order is preserved, so the burst rung stays exactly where the factory put it: last.
    Returns the list unchanged when there is no burst rung in it, which is the default
    configuration and must stay free of surprises.
    """
    if burst_rung_allows(feature=feature, cost_tier=cost_tier):
        return list(providers)
    return [p for p in providers if not is_burst_rung(p)]
