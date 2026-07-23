"""
Structured AI generation with provider fallback — services/ai/generate.py

One place that every AI-backed feature (answer evaluation, question and quiz
generation, report generation) goes through to get a validated, typed result
from the model. It centralizes what used to be duplicated per call site:

  - Try the primary provider; on failure fall through to the fallback
    (see provider_factory.get_ai_providers) — doubles effective capacity and
    survives one provider being down/slow.
  - Retry each provider a few times, since the free-tier reasoning models
    intermittently return empty or malformed content.
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

from .base_provider import ProviderError, ProviderMessage, ProviderRequest
from .json_validator import AIValidationError, JSONValidator
from .provider_factory import get_ai_providers
from .response_parser import ResponseParser

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_parser = ResponseParser(JSONValidator())


async def generate_structured(
    schema: type[T],
    messages: list[ProviderMessage],
    *,
    max_tokens: int,
    temperature: float = 0.7,
    attempts_per_provider: int = 2,
    is_valid: Callable[[T], bool] | None = None,
    context: str = "ai_generation",
) -> tuple[T, str]:
    """
    Generate a validated `schema` instance from the model, trying each provider
    in the chain with retries. Returns (parsed, raw_content).

    Raises AIProviderUnavailableError if no provider produced a valid result.
    """
    providers = get_ai_providers()
    last_raw = ""

    for provider in providers:
        for attempt in range(attempts_per_provider):
            try:
                resp = await provider.complete(
                    ProviderRequest(
                        messages=messages,
                        json_mode=True,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                )
            except ProviderError:
                logger.warning(
                    "ai_generate_provider_error",
                    context=context,
                    provider=provider.provider_name,
                    attempt=attempt,
                )
                continue

            last_raw = resp.content
            try:
                parsed = _parser.parse(resp.content, schema)
            except AIValidationError:
                logger.warning(
                    "ai_generate_validation_failed",
                    context=context,
                    provider=provider.provider_name,
                    attempt=attempt,
                )
                continue

            if is_valid is not None and not is_valid(parsed):
                logger.warning(
                    "ai_generate_result_rejected",
                    context=context,
                    provider=provider.provider_name,
                    attempt=attempt,
                )
                continue

            return parsed, last_raw

        if len(providers) > 1:
            logger.warning("ai_generate_falling_back", context=context, exhausted=provider.provider_name)

    raise AIProviderUnavailableError(provider=providers[0].provider_name if providers else "unknown")
