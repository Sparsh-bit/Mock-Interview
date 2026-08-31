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

import structlog

from .base_provider import CostTier

logger = structlog.get_logger(__name__)

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


# ─────────────────────────────────────────────────────────────────────────────
# CAPACITY, WHICH THE POLICY ABOVE DELIBERATELY IS NOT.
#
# The module docstring says in as many words that the rung "is not capacity" — that gate
# answers WHICH CALLS may reach a model we do not pay for, and it would still say yes on the
# two-thousand-and-first request of the day. Groq's free plan is counted in REQUESTS, not
# dollars, so `AI_DAILY_BUDGET_USD` cannot see it: a free call costs $0.00 and the spend cap
# never moves.
#
# Past the ceiling Groq answers 429. Nothing breaks — the chain has already exhausted the paid
# providers by the time it gets here, so the call fails either way — but it fails after a round
# trip and a retry, and it puts the account in a rate-limited state that the NEXT deploy's
# health check reports as a provider outage. Refusing locally is faster and truthful.
#
# THE COUNT IS THE HIGHER OF REDIS AND THIS PROCESS'S OWN TALLY, the same shape the AI spend
# cap uses: neither source failing can under-report, and under-reporting is the only direction
# that costs anything.
#
# IT RESERVES BEFORE THE CALL, not after. Incrementing on success would let a burst of
# concurrent requests all read 1,999 and all proceed. Counting an attempt that then fails is
# the conservative error, and "must not exceed" is the requirement.
# ─────────────────────────────────────────────────────────────────────────────

#: Per-process tally, used when Redis is unreachable. A single replica then still caps itself;
#: several replicas each cap themselves, so the fleet ceiling becomes limit x replicas. That is
#: a degradation of an already-degraded state, and the alternative — refusing the rung entirely
#: whenever Redis blinks — throws away the fallback at exactly the moment the paid providers
#: are already failing.
_local_requests: dict[str, int] = {}


def _today_key() -> str:
    """UTC, because the process timezone is not a thing to depend on across hosts."""
    from datetime import UTC, datetime  # noqa: PLC0415

    return f"ai:rung:requests:{datetime.now(UTC).date().isoformat()}"


async def rung_requests_today() -> int:
    """How many rung calls have been reserved today, across the fleet where possible."""
    key = _today_key()
    local = _local_requests.get(key, 0)

    from app.db.redis import cache_get, get_redis  # noqa: PLC0415

    try:
        raw = await cache_get(get_redis(), key)
        shared = int(raw) if raw else 0
    except Exception:  # noqa: BLE001 — accounting must never break a request
        logger.warning("rung_request_count_read_failed_using_local", local=local)
        return local
    return max(local, shared)


async def note_rung_request() -> None:
    """Reserve one request against today's allowance."""
    key = _today_key()
    _local_requests[key] = _local_requests.get(key, 0) + 1
    # Keep the dict from growing without bound across a long-lived process.
    for stale in [k for k in _local_requests if k != key]:
        _local_requests.pop(stale, None)

    from app.db.redis import get_redis  # noqa: PLC0415

    try:
        redis = get_redis()
        count = await redis.incr(key)
        # Set the expiry only on the first write of the day, so a mid-day INCR cannot keep
        # pushing the window out and leave yesterday's count alive into tomorrow.
        if count == 1:
            await redis.expire(key, 60 * 60 * 36)
    except Exception:  # noqa: BLE001
        logger.warning("rung_request_count_write_failed_local_only", local=_local_requests[key])


async def rung_has_budget(limit: int) -> bool:
    """
    False once today's allowance is spent. `limit <= 0` disables the cap.

    Read separately from `eligible_providers` on purpose: that function is pure policy and is
    called synchronously in five tests. This is the only part that needs Redis, and keeping the
    two apart means the policy stays trivially testable.
    """
    if limit <= 0:
        return True
    used = await rung_requests_today()
    if used < limit:
        return True
    logger.warning("burst_rung_daily_request_limit_reached", used=used, limit=limit)
    return False
