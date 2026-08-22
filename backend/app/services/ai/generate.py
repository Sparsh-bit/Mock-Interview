"""
Structured AI generation with provider fallback — services/ai/generate.py

One place that every AI-backed feature (answer evaluation, question and quiz
generation, report generation) goes through to get a validated, typed result
from the model. It centralizes what used to be duplicated per call site:

  - Try the primary provider; on failure fall through to the fallback
    (see provider_factory.get_ai_providers) — doubles effective capacity and
    survives one provider being down/slow.
  - Retry each provider a few times, since a provider can intermittently return
    empty or malformed content even on a success status.
  - Parse + Pydantic-validate the response, with an optional `is_valid`
    predicate for "schema-valid but useless" cases (e.g. an empty quiz).
  - Fail closed with AIProviderUnavailableError only after every provider and
    attempt is exhausted — never fabricate a result.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import structlog
from pydantic import BaseModel

from app.core.exceptions import AIProviderUnavailableError

from .base_provider import CostTier, ProviderError, ProviderMessage, ProviderRequest
from .json_validator import AIValidationError, JSONValidator
from .provider_factory import get_ai_providers
from .response_parser import ResponseParser
from .usage import record_call

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_parser = ResponseParser(JSONValidator())


async def generate_structured(
    schema: type[T],
    messages: list[ProviderMessage],
    *,
    max_tokens: int,
    temperature: float = 0.7,
    cost_tier: CostTier = CostTier.BALANCED,
    attempts_per_provider: int = 2,
    is_valid: Callable[[T], bool] | None = None,
    context: str = "ai_generation",
    cache_system: bool = False,
) -> tuple[T, str]:
    """
    Generate a validated `schema` instance from the model, trying each provider
    in the chain with retries. Returns (parsed, raw_content).

    `cost_tier` declares how much reasoning the task is worth paying for on
    metered providers (see CostTier); free-tier providers ignore it. Pass it at
    every call site — the default is deliberately mid-range, not cheapest.

    `cache_system` declares that this call's system block is byte-identical across
    requests, so marking it cacheable produces reads rather than only writes. Set it ONLY
    from a call site whose prompt template carries no per-request substitutions — a cache
    write bills at 1.25x input, so getting this wrong costs 25% extra on every call
    forever and never reads. See prompts/gd_panel.md and its test.

    Raises AIProviderUnavailableError if no provider produced a valid result.
    """
    providers = get_ai_providers()
    last_raw = ""
    spend_usd = 0.0

    for provider in providers:
        for attempt in range(attempts_per_provider):
            try:
                resp = await provider.complete(
                    ProviderRequest(
                        messages=messages,
                        json_mode=True,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        cost_tier=cost_tier,
                        cache_system=cache_system,
                    )
                )
            except ProviderError as exc:
                # THE REASON, NOT JUST THE FACT. This logged the context, the provider and the
                # attempt number and nothing about what went wrong — so a production warning
                # read "anthropic failed" and left no way to tell a missing API key from a
                # rate limit from a wrong model name from an outage. All four look identical
                # in the logs and want completely different responses, and the interview
                # silently continues on the fallback provider meanwhile, so nothing else
                # surfaces it either.
                #
                # Reported from a live Render log: an `ai_generate_provider_error` for
                # `interview_plan` on `anthropic`, immediately followed by
                # `ai_generate_falling_back`, with no reason recorded anywhere. Same class of
                # defect as the Fish client raising ReadTimeout with an empty message.
                #
                # The exception TYPE is included as well as its text because a provider SDK
                # can raise with an empty string — the type is then the only diagnostic left.
                logger.warning(
                    "ai_generate_provider_error",
                    context=context,
                    provider=provider.provider_name,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    error=str(exc) or type(exc).__name__,
                )
                continue

            # Every completed call is billed, including ones we reject below —
            # so accumulate before validating, not after.
            spend_usd += resp.estimated_cost_usd or 0.0

            last_raw = resp.content
            try:
                parsed = _parser.parse(resp.content, schema)
            except AIValidationError:
                # THE FINISH REASON IS THE DIAGNOSIS, so log it here and not only in
                # the provider. `finish_reason="length"` means the answer was cut off
                # by this call site's max_tokens — a retry will hit the same ceiling in
                # the same place, so the fix is the ceiling, not the retry. Resume
                # analysis burned four billed calls per upload that way for months: the
                # providers each logged a truncation warning, but neither said which
                # FEATURE it belonged to, so nothing connected the warning to uploads
                # coming back with no skills.
                logger.warning(
                    "ai_generate_validation_failed",
                    context=context,
                    provider=provider.provider_name,
                    attempt=attempt,
                    finish_reason=resp.finish_reason,
                    completion_tokens=resp.completion_tokens,
                    max_tokens=max_tokens,
                )
                # TEMPORARY (token counter). This call was billed in full and its
                # output is unusable. Recording it is the whole point: a feature
                # whose discarded spend is a third of its total has a prompt
                # problem, and success-only accounting cannot show that.
                await record_call(
                    feature=context,
                    provider=provider.provider_name,
                    response=resp,
                    cost_tier=cost_tier.value,
                    outcome="discarded",
                )
                continue

            if is_valid is not None and not is_valid(parsed):
                logger.warning(
                    "ai_generate_result_rejected",
                    context=context,
                    provider=provider.provider_name,
                    attempt=attempt,
                )
                # TEMPORARY (token counter) — billed, parsed, and still rejected.
                await record_call(
                    feature=context,
                    provider=provider.provider_name,
                    response=resp,
                    cost_tier=cost_tier.value,
                    outcome="discarded",
                )
                continue

            if spend_usd:
                logger.info(
                    "ai_generate_spend",
                    context=context,
                    provider=provider.provider_name,
                    cost_tier=cost_tier.value,
                    billed_calls=attempt + 1,
                    estimated_cost_usd=round(spend_usd, 6),
                )
            # TEMPORARY (token counter) — see services/ai/usage.py.
            await record_call(
                feature=context,
                provider=provider.provider_name,
                response=resp,
                cost_tier=cost_tier.value,
                outcome="ok",
            )
            return parsed, last_raw

        if len(providers) > 1:
            logger.warning("ai_generate_falling_back", context=context, exhausted=provider.provider_name)

    # Wasted spend: every attempt was billed and none produced a usable result.
    logger.error(
        "ai_generate_exhausted",
        context=context,
        cost_tier=cost_tier.value,
        wasted_cost_usd=round(spend_usd, 6),
    )
    raise AIProviderUnavailableError(provider=providers[0].provider_name if providers else "unknown")
