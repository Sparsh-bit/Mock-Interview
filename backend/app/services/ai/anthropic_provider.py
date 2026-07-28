"""
Anthropic Claude provider — anthropic_provider.py

The paid, production AI provider for InterviewOS, built for a small fixed
budget. Uses the official `anthropic` SDK Messages API.

Configuration:
    AI_PROVIDER=anthropic
    AI_FALLBACK_PROVIDER=glm          # free-tier safety net if credit runs out
    ANTHROPIC_API_KEY=sk-ant-...
    ANTHROPIC_MODEL=claude-sonnet-5

── Cost control (why this file looks the way it does) ───────────────────────
Output tokens cost 5x input, and Claude's *reasoning* tokens bill as output.
Four levers, in descending order of impact:

1. Reasoning budget. Sonnet 5 runs adaptive thinking **by default when the
   `thinking` field is omitted** — so saying nothing silently buys reasoning on
   every call. We always set it explicitly from the request's CostTier, and
   only the final report pays for thinking.
2. A daily spend cap (AI_DAILY_BUDGET_USD). Checked in Redis before every call;
   once hit we raise ProviderError so the chain degrades to the free provider
   instead of draining the balance.
3. Output ceiling. Every call is clamped to ANTHROPIC_MAX_OUTPUT_TOKENS on top
   of the call site's own max_tokens, so one runaway response can't drain the
   balance.
4. Not calling at all — handled upstream by the Redis/semantic plan cache.

Prompt caching is supported but OFF by default, which is counter-intuitive
enough to spell out: PromptBuilder substitutes per-request variables into the
*system* template, so every request has a unique prefix. Enabling it would bill
a cache write at 1.25x input on every call and never score a read — worse than
not caching. It only pays off once prompts are restructured to keep the system
block byte-identical, with the variables moved into the user turn.

── Two API constraints this provider absorbs ────────────────────────────────
Sonnet 5 rejects things the OpenAI-compatible providers accept, so the
translation layer is not a passthrough:

* `temperature` / `top_p` / `top_k` are rejected with a 400. ProviderRequest
  carries a temperature for the GLM/NVIDIA path; we drop it here.
* A trailing assistant message (response prefill) is rejected with a 400.
"""

from __future__ import annotations

from datetime import UTC

import anthropic
import structlog

from .base_provider import (
    BaseAIProvider,
    CostTier,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
)

logger = structlog.get_logger(__name__)

# ─── Daily spend circuit breaker ──────────────────────────────────────────────


async def _spend_key() -> str:
    """Redis key holding today's total metered spend (UTC day)."""
    from datetime import datetime  # noqa: PLC0415

    return f"ai:spend:{datetime.now(UTC):%Y-%m-%d}"


# In-process spend fallback, keyed by UTC day.
#
# Redis is the source of truth because it is shared across workers, but a money
# guard must not fail OPEN: if Redis is unreachable, a Redis-only implementation
# reads 0.0 forever and the cap silently stops existing. This local counter means
# an unlimited-spend window can never open — worst case (Redis down, N workers)
# the effective ceiling is per-worker rather than global.
_local_spend: dict[str, float] = {}


async def _spend_today() -> float:
    """
    Total USD spent today — the higher of the shared Redis counter and this
    process's own tally, so neither source failing can under-report.
    """
    key = await _spend_key()
    local = _local_spend.get(key, 0.0)

    from app.db.redis import cache_get, get_redis  # noqa: PLC0415

    try:
        raw = await cache_get(get_redis(), key)
        shared = float(raw) if raw else 0.0
    except Exception:  # noqa: BLE001 — never let accounting break a request
        logger.warning("ai_spend_read_failed_using_local", local_usd=round(local, 4))
        return local

    return max(shared, local)


async def _record_spend(amount: float) -> None:
    """Add to today's spend counters. Local first so it cannot be skipped."""
    if amount <= 0:
        return

    key = await _spend_key()
    # Record locally before the network call — if Redis throws, the spend is
    # still counted and the cap still converges.
    _local_spend[key] = _local_spend.get(key, 0.0) + amount
    # Keep only the current day; this dict must not grow forever.
    for stale in [k for k in _local_spend if k != key]:
        del _local_spend[stale]

    from app.db.redis import get_redis  # noqa: PLC0415

    try:
        redis = get_redis()
        await redis.incrbyfloat(key, amount)
        # Expire well after the day rolls over so the key can't leak forever.
        await redis.expire(key, 60 * 60 * 48)
    except Exception:  # noqa: BLE001
        logger.warning("ai_spend_record_failed_counted_locally", amount=amount)


class BudgetExceededError(ProviderError):
    """
    Today's metered AI budget is spent.

    Subclasses ProviderError so generate_structured's existing handling moves on
    to the next provider in the chain — i.e. the app degrades to the free
    provider rather than failing or overspending.
    """

# ─── Price sheet (USD per million tokens) ─────────────────────────────────────
# Used only to log an estimated per-call cost so spend is observable without
# opening the Anthropic console. Sonnet 5 list price is $3/$15; the promotional
# $2/$10 runs through 2026-08-31, so these estimates are a conservative
# upper bound while the intro rate applies. Cache reads bill at ~0.1x input,
# cache writes at ~1.25x.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
_DEFAULT_PRICE = (3.00, 15.00)

# ─── CostTier → Claude reasoning parameters ───────────────────────────────────
# `effort` caps overall token spend; `thinking` decides whether we buy
# reasoning at all. Sonnet 5 accepts thinking:{"type":"disabled"} (unlike
# Fable 5), and we never pair disabled thinking with xhigh/max effort.
#
# Values are (thinking_enabled, effort).
_TIER_PARAMS: dict[CostTier, tuple[bool, str]] = {
    CostTier.CHEAP: (False, "low"),
    CostTier.BALANCED: (False, "medium"),
    CostTier.DEEP: (True, "medium"),
}

# When thinking is on, `max_tokens` is a combined ceiling for reasoning AND the
# visible answer — a tight budget yields a truncated response. Guarantee this
# much room before enabling it; below that we drop to non-thinking rather than
# pay for reasoning we'd then truncate.
_MIN_TOKENS_FOR_THINKING = 3072

# Above this, non-streaming requests risk an SDK HTTP timeout.
_STREAMING_THRESHOLD = 16_000


class AnthropicProvider(BaseAIProvider):
    """
    Claude provider via the official Anthropic Python SDK.

    Stateless between requests and safe to reuse process-wide; the SDK client
    holds a pooled HTTP connection.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        provider_name: str = "anthropic",
        *,
        prompt_caching: bool = False,
        max_output_tokens: int = 4096,
        daily_budget_usd: float = 2.0,
        timeout: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        if not api_key:
            raise ValueError("anthropic provider requires a non-empty api_key.")
        self._model = model
        self._provider_name = provider_name
        self._prompt_caching = prompt_caching
        self._max_output_tokens = max_output_tokens
        self._daily_budget_usd = daily_budget_usd
        # max_retries covers 429/5xx/connection errors with backoff in-SDK.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )

    # ─── BaseAIProvider interface ─────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        # Refuse before spending, not after. Raising ProviderError lets the
        # generation layer fall through to the free provider, so features keep
        # working once the daily budget is gone.
        if self._daily_budget_usd > 0:
            spent = await _spend_today()
            if spent >= self._daily_budget_usd:
                logger.error(
                    "ai_daily_budget_exceeded",
                    spent_usd=round(spent, 4),
                    budget_usd=self._daily_budget_usd,
                )
                raise BudgetExceededError(
                    f"Daily AI budget of ${self._daily_budget_usd:.2f} reached "
                    f"(${spent:.4f} spent). Falling back to the free provider.",
                    provider=self.provider_name,
                )

        model = request.model_override or self._model
        system_blocks, messages = self._split_messages(request)

        # Clamp output. The call site asked for max_tokens; the budget guard
        # gets the final say.
        max_tokens = min(request.max_tokens, self._max_output_tokens)

        thinking_enabled, effort = _TIER_PARAMS[request.cost_tier]
        if thinking_enabled and max_tokens < _MIN_TOKENS_FOR_THINKING:
            # Not enough headroom for reasoning + a complete answer.
            logger.debug(
                "anthropic_thinking_skipped_low_budget",
                max_tokens=max_tokens,
                required=_MIN_TOKENS_FOR_THINKING,
            )
            thinking_enabled = False

        payload: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            # Explicit either way: omitting `thinking` on Sonnet 5 silently
            # enables adaptive reasoning and bills for it.
            "thinking": {"type": "adaptive"} if thinking_enabled else {"type": "disabled"},
            "output_config": {"effort": effort},
        }
        if system_blocks:
            payload["system"] = system_blocks

        # NOTE: request.temperature is intentionally not forwarded — Sonnet 5
        # returns a 400 for non-default sampling parameters.

        log = logger.bind(
            provider=self.provider_name,
            model=model,
            cost_tier=request.cost_tier.value,
            effort=effort,
            thinking=thinking_enabled,
            max_tokens=max_tokens,
            cache_enabled=self._prompt_caching,
        )
        log.debug("provider_request_start")

        try:
            if max_tokens > _STREAMING_THRESHOLD:
                # Large outputs must stream or the HTTP request can time out.
                async with self._client.messages.stream(**payload) as stream:
                    message = await stream.get_final_message()
            else:
                message = await self._client.messages.create(**payload)
        except anthropic.APIStatusError as exc:
            body = str(exc.message)[:500]
            log.error("provider_api_error", status_code=exc.status_code, body=body)
            raise ProviderError(
                f"anthropic API returned {exc.status_code}: {body}",
                provider=self.provider_name,
                status_code=exc.status_code,
                raw_error=body,
            ) from exc
        except anthropic.APIConnectionError as exc:
            # Covers timeouts (APITimeoutError is a subclass) and network errors.
            log.error("provider_network_error", error=str(exc))
            raise ProviderError(
                f"anthropic connection error: {exc}",
                provider=self.provider_name,
            ) from exc

        response = self._to_response(message, model, log)
        await _record_spend(response.estimated_cost_usd or 0.0)
        return response

    async def health_check(self) -> bool:
        """
        Cheapest possible liveness probe: 1 output token, no reasoning, no
        cache write. Never raises — returns False on failure.
        """
        try:
            await self._client.messages.create(
                model=self._model,
                max_tokens=1,
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            logger.exception("provider_health_check_failed", provider=self.provider_name)
            return False

    async def close(self) -> None:
        await self._client.close()

    # ─── Translation helpers ──────────────────────────────────────────────

    def _split_messages(
        self, request: ProviderRequest
    ) -> tuple[list[dict], list[dict]]:
        """
        Split our flat message list into Claude's (system, messages) shape.

        Claude takes the system prompt as a top-level parameter rather than a
        message. We concatenate any system messages into one text block and,
        when caching is on, mark it as a cache breakpoint — `tools` and
        `system` render before `messages`, so a marker on the last system
        block caches the whole stable prefix.
        """
        system_parts: list[str] = []
        turns: list[dict] = []

        for msg in request.messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            else:
                turns.append({"role": msg.role, "content": msg.content})

        # A trailing assistant turn is a response prefill, which Sonnet 5
        # rejects with a 400. No current call site builds one; drop it loudly
        # so a future change degrades instead of breaking the interview.
        while turns and turns[-1]["role"] == "assistant":
            logger.warning(
                "anthropic_dropped_trailing_assistant_prefill",
                reason="response prefill is rejected by Claude Sonnet 5",
            )
            turns.pop()

        # The messages array may not be empty and must open on a user turn.
        if not turns:
            turns = [{"role": "user", "content": "Proceed."}]
        elif turns[0]["role"] != "user":
            turns.insert(0, {"role": "user", "content": "Proceed."})

        if not system_parts:
            return [], turns

        block: dict = {"type": "text", "text": "\n\n".join(system_parts)}
        if self._prompt_caching:
            # Sonnet 5 only caches prefixes >= 1024 tokens. Shorter prompts
            # silently don't cache (no error, no charge) — verify with the
            # cache_read_input_tokens we log below.
            block["cache_control"] = {"type": "ephemeral"}
        return [block], turns

    def _to_response(
        self, message: anthropic.types.Message, model: str, log: structlog.BoundLogger
    ) -> ProviderResponse:
        """Normalize a Claude Message into ProviderResponse."""
        # Check stop_reason before reading content: on a refusal `content` is
        # empty or partial, so indexing it blindly would raise.
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None)
            log.error("provider_refusal", category=category)
            raise ProviderError(
                f"anthropic declined the request (category={category}). "
                "The prompt likely tripped a safety classifier.",
                provider=self.provider_name,
                raw_error=category,
            )

        # Concatenate text blocks, skipping thinking blocks (which carry no
        # text under the default display setting anyway).
        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )

        usage = message.usage
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        # `input_tokens` is the uncached remainder only — cached and written
        # tokens are reported separately, so total input is the sum.
        uncached_in = usage.input_tokens or 0
        out = usage.output_tokens or 0

        in_price, out_price = _PRICE_PER_MTOK.get(model, _DEFAULT_PRICE)
        cost = (
            uncached_in * in_price
            + cache_write * in_price * 1.25
            + cached * in_price * 0.10
            + out * out_price
        ) / 1_000_000

        log.info(
            "provider_request_complete",
            stop_reason=message.stop_reason,
            input_tokens=uncached_in,
            cached_input_tokens=cached,
            cache_write_tokens=cache_write,
            output_tokens=out,
            estimated_cost_usd=round(cost, 6),
        )

        if message.stop_reason == "max_tokens":
            # Surfaces as a JSON parse failure downstream; name the real cause.
            log.warning(
                "anthropic_output_truncated",
                hint="raise the call site's max_tokens or ANTHROPIC_MAX_OUTPUT_TOKENS",
            )

        return ProviderResponse(
            content=text,
            model=message.model,
            prompt_tokens=uncached_in + cached + cache_write,
            completion_tokens=out,
            finish_reason=message.stop_reason or "stop",
            cached_input_tokens=cached,
            cache_write_tokens=cache_write,
            estimated_cost_usd=round(cost, 6),
        )
