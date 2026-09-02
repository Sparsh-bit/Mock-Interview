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

from collections.abc import AsyncIterator
from datetime import UTC

import anthropic
import structlog
from anthropic.types import TextBlock

from .base_provider import (
    BaseAIProvider,
    CostTier,
    ProviderError,
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    StreamChunk,
)
from .model_routing import wants_cheap_model

logger = structlog.get_logger(__name__)

# ─── Daily spend circuit breaker ──────────────────────────────────────────────


async def _spend_key(scope: str = "") -> str:
    """
    Redis key holding today's metered spend (UTC day).

    `scope` empty means the whole product; a user id scopes it to that user. Same
    key shape and same expiry for both, so the per-user cap inherits the
    fail-closed behaviour the global one already has.
    """
    from datetime import datetime  # noqa: PLC0415

    day = f"{datetime.now(UTC):%Y-%m-%d}"
    return f"ai:spend:{day}:{scope}" if scope else f"ai:spend:{day}"


# In-process spend fallback, keyed by UTC day.
#
# Redis is the source of truth because it is shared across workers, but a money
# guard must not fail OPEN: if Redis is unreachable, a Redis-only implementation
# reads 0.0 forever and the cap silently stops existing. This local counter means
# an unlimited-spend window can never open — worst case (Redis down, N workers)
# the effective ceiling is per-worker rather than global.
_local_spend: dict[str, float] = {}


async def _spend_today(scope: str = "") -> float:
    """
    USD spent today — the higher of the shared Redis counter and this process's own
    tally, so neither source failing can under-report.

    `scope` empty for the product total, a user id for one user.
    """
    key = await _spend_key(scope)
    local = _local_spend.get(key, 0.0)

    from app.db.redis import cache_get, get_redis  # noqa: PLC0415

    try:
        raw = await cache_get(get_redis(), key)
        shared = float(raw) if raw else 0.0
    except Exception:  # noqa: BLE001 — never let accounting break a request
        logger.warning("ai_spend_read_failed_using_local", local_usd=round(local, 4))
        return local

    return max(shared, local)


async def _record_spend(amount: float, scope: str = "") -> None:
    """Add to today's spend counters. Local first so it cannot be skipped."""
    if amount <= 0:
        return

    key = await _spend_key(scope)
    # Record locally before the network call — if Redis throws, the spend is
    # still counted and the cap still converges.
    _local_spend[key] = _local_spend.get(key, 0.0) + amount
    # Keep only the current day; this dict must not grow forever. Matched on the DAY
    # prefix, not the whole key — there is now one entry per user per day, and the
    # original `k != key` would have deleted every OTHER user's tally on every call,
    # so no per-user cap could ever accumulate.
    day_prefix = ":".join(key.split(":")[:3])  # ai:spend:YYYY-MM-DD
    for stale in [k for k in _local_spend if not k.startswith(day_prefix)]:
        del _local_spend[stale]

    from app.db.redis import get_redis  # noqa: PLC0415

    try:
        redis = get_redis()
        await redis.incrbyfloat(key, amount)
        # Expire well after the day rolls over so the key can't leak forever.
        await redis.expire(key, 60 * 60 * 48)
    except Exception:  # noqa: BLE001
        logger.warning("ai_spend_record_failed_counted_locally", amount=amount)


def _current_user_is_admin() -> bool:
    """
    Is this request's user an admin? Never raises; False when unknown.

    Read from the contextvar core/security.py sets beside the user id, so it needs no change
    at any generate_structured call site and cannot be forgotten at a new one. False on any
    failure, so the fallback is to METER — an exemption that fires by accident is a bill
    nobody chose.
    """
    try:
        from app.services.ai.usage import current_user_is_admin  # noqa: PLC0415

        return bool(current_user_is_admin.get())
    except Exception:  # noqa: BLE001 — metering must never fail a request
        return False


def _current_user_scope() -> str | None:
    """
    The authenticated user for this request, as a spend scope, or None.

    Read from the contextvar core/security.py already sets — so per-user metering
    needs no change at any of the thirteen generate_structured call sites, and cannot
    be forgotten at a new one.
    """
    try:
        from app.services.ai.usage import current_user_id  # noqa: PLC0415

        uid = current_user_id.get()
        return str(uid) if uid else None
    except Exception:  # noqa: BLE001 — accounting must never break a request
        return None


class BudgetExceededError(ProviderError):
    """
    Today's metered AI budget is spent, PRODUCT-WIDE.

    Subclasses ProviderError so generate_structured's existing handling moves on
    to the next provider in the chain — i.e. the app degrades to the free
    provider rather than failing or overspending.

    This is an operations alarm, not a user-facing limit. It means the circuit
    breaker tripped and EVERY user is now on the free provider, so it should page
    somebody rather than be shown to a candidate as though they did something.
    """


class UserBudgetExceededError(BudgetExceededError):
    """
    ONE user has spent their own daily allowance.

    Distinct from the global breaker because the two need completely different
    handling. This one is normal, expected, and about a single person: they have
    had a lot of practice today, they stay on the free provider until the UTC day
    rolls over, and nothing is wrong with the service.

    Kept as a subclass so existing `except BudgetExceededError` handling keeps
    working — the fallback to the free provider is the right behaviour for both.
    What differs is what the user is told, which is why the two exist at all.
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

#: What the Message Batches API bills, as a multiplier on the standard price.
#:
#: Anthropic discounts batched input AND output by 50%. This is not a cache and does not
#: interact with one — a batched request whose system block is also cached pays 0.5x the
#: already-reduced cache-read rate. It is the largest single saving available on the report,
#: which is the one call in this product nobody is waiting on: see docs/AI-COST-MODEL.md.
_BATCH_PRICE_MULTIPLIER = 0.5

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

# ─── What each model will actually accept ─────────────────────────────────────
#
# NOT EVERY CLAUDE MODEL TAKES THE SAME PARAMETERS, and finding that out costs a 400 per
# call rather than a degraded answer. Measured against the live API while wiring CostTier.
# CHEAP to Haiku:
#
#   claude-haiku-4-5   output_config.effort      -> 400 "This model does not support the
#                                                   effort parameter"
#                      thinking {type: adaptive} -> 400 "adaptive thinking is not supported"
#                      thinking {type: disabled} -> fine
#                      temperature               -> fine (unlike Sonnet 5, which rejects it)
#
# THE FIRST TWO WOULD HAVE BEEN INVISIBLE IN THE WORST WAY. A panel turn that 400s produces
# no turns, the caller falls back to putting the bare question, and the candidate sees the
# interview continue — slightly flatter, with the bank's own wording. That exact symptom
# ("sometimes the old UI comes in with the different question") already cost this repo a
# four-round investigation that went looking in the TTS layer. So the constraint is absorbed
# here, beside the two this provider already absorbs, rather than left to fail per call.
#
# (supports_effort, supports_adaptive_thinking). Anything not listed defaults to True/True,
# which is the Sonnet/Opus family behaviour and the safe assumption for a model added later:
# being wrong that way is one loud 400 on a new model, while defaulting to False would
# silently stop buying reasoning on a DEEP call and nothing would say so.
_MODEL_CAPABILITIES: dict[str, tuple[bool, bool]] = {
    "claude-haiku-4-5": (False, False),
}
_DEFAULT_CAPABILITIES = (True, True)

# When thinking is on, `max_tokens` is a combined ceiling for reasoning AND the
# visible answer — a tight budget yields a truncated response. Guarantee this
# much room before enabling it; below that we drop to non-thinking rather than
# pay for reasoning we'd then truncate.
_MIN_TOKENS_FOR_THINKING = 3072

# Above this, non-streaming requests risk an SDK HTTP timeout.
_STREAMING_THRESHOLD = 16_000


def _turn_content(message: ProviderMessage) -> str | list[dict]:
    """
    One conversation turn's content in Claude's shape.

    A TEXT-ONLY TURN STAYS A PLAIN STRING. Claude accepts either, and every existing call
    in this application sends the string — keeping it means adding vision changes the wire
    format of exactly the calls that use vision, and of nothing else.

    IMAGE BLOCKS COME FIRST, TEXT LAST. Anthropic's own guidance is that Claude attends
    better to a question asked after the images it is about than to one asked before them,
    and this order is the documented recommendation for multi-image prompts. The OpenAI
    translator puts text first because that is the shape its examples use; the two
    providers legitimately differ here, which is the whole reason each one owns its own
    translation.
    """
    if not message.images:
        return message.content
    blocks: list[dict] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image.media_type,
                "data": image.base64_data,
            },
        }
        for image in message.images
    ]
    blocks.append({"type": "text", "text": message.content})
    return blocks


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
        cheap_model: str = "",
        prompt_caching: bool = False,
        max_output_tokens: int = 4096,
        daily_budget_usd: float = 2.0,
        user_daily_budget_usd: float = 0.0,
        timeout: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        if not api_key:
            raise ValueError("anthropic provider requires a non-empty api_key.")
        self._model = model
        #: What a CHEAP call on an allowlisted feature runs on instead. EMPTY MEANS OFF,
        #: and that is the one-line way to undo the routing without a deploy: every call
        #: falls back to `model` and nothing else changes.
        self._cheap_model = (cheap_model or "").strip()
        self._provider_name = provider_name
        self._prompt_caching = prompt_caching
        self._user_daily_budget_usd = user_daily_budget_usd
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

    def _select_model(self, request: ProviderRequest) -> str:
        """
        The configured model, or the cheap one when policy says this call may have it.

        THE POLICY IS NOT HERE, DELIBERATELY. `model_routing.wants_cheap_model` decides
        which features tolerate a smaller model, because that is a fact about the feature
        rather than about Anthropic — base_provider.py's rule that an implementation carries
        no business logic, and the same split burst_rung.py already makes. What lives here
        is the only genuinely vendor-shaped part: the model's NAME.

        Falls through to the configured model whenever `cheap_model` is empty, which is what
        makes clearing ANTHROPIC_CHEAP_MODEL a complete off switch.
        """
        if not self._cheap_model:
            return self._model
        if wants_cheap_model(feature=request.feature, cost_tier=request.cost_tier):
            return self._cheap_model
        return self._model

    def _build_payload(
        self, request: ProviderRequest
    ) -> tuple[dict, str, int, bool, str]:
        """
        Translate a ProviderRequest into a Claude Messages payload.

        EXTRACTED SO THE BATCH PATH CANNOT DRIFT FROM THE LIVE ONE. A batched request is
        the same request, submitted differently — the model, the output clamp, the
        thinking/effort mapping and the system/messages split must all be identical, or a
        report generated in a batch is a different report from one generated live and
        nobody would find out from a test that only exercises one of them.

        Returns the payload plus the four derived values the caller logs.
        """
        model = request.model_override or self._select_model(request)
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

        supports_effort, supports_adaptive = _MODEL_CAPABILITIES.get(
            model, _DEFAULT_CAPABILITIES
        )
        if thinking_enabled and not supports_adaptive:
            # DEGRADED, NOT REFUSED, and loudly. Reaching here means a tier that wanted
            # reasoning has been pointed at a model that cannot do it — a configuration
            # mistake rather than a runtime condition. Failing the call would take the
            # feature down; sending it anyway is a guaranteed 400. Answering without
            # reasoning is the only option that produces an answer, and the log line is
            # what stops it being mistaken for the reasoning having happened.
            logger.warning(
                "anthropic_adaptive_thinking_unsupported_on_model",
                model=model,
                cost_tier=request.cost_tier.value,
                hint="this model has no adaptive thinking; the call ran without it",
            )
            thinking_enabled = False

        payload: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            # Explicit either way: omitting `thinking` on Sonnet 5 silently
            # enables adaptive reasoning and bills for it.
            "thinking": {"type": "adaptive"} if thinking_enabled else {"type": "disabled"},
        }
        if supports_effort:
            # OMITTED ENTIRELY rather than sent with some neutral value, because Haiku 4.5
            # rejects the FIELD, not a particular value of it. There is nothing to lose:
            # effort caps overall token spend, and a model without the knob is already the
            # cheap one.
            payload["output_config"] = {"effort": effort}
        if system_blocks:
            payload["system"] = system_blocks

        # NOTE: request.temperature is intentionally not forwarded — Sonnet 5
        # returns a 400 for non-default sampling parameters.
        return payload, model, max_tokens, thinking_enabled, effort

    async def _refuse_if_over_budget(self) -> None:
        """
        Stop before spending, not after.

        EXTRACTED SO STREAMING CANNOT SKIP IT. This was inline in `complete`, which was
        correct while `complete` was the only way to spend money here. `stream_text` is a
        second one, and a guard that lives inside one caller is a guard the other caller
        silently does not have — the failure being "the daily breaker works, except on the
        path nobody remembered", which is invisible until the bill arrives.
        """
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

        # Then the per-user allowance. Checked SECOND: if the product-wide breaker has
        # tripped, that is the more urgent fact and the one worth logging.
        # ADMINS ARE NOT METERED, for the reason services/billing/credits.py gives for not
        # metering their credits: it is the only way the product can be operated. Every check
        # that an interview still works, every reproduction of a reported bug and every demo
        # runs through the paths a candidate uses. Metering the operator means they spend
        # their allowance on Tuesday and then test the STANDBY provider for the rest of the
        # day while believing they are testing the product — which is quieter than a failure
        # and makes the app look slower and worse than it is.
        #
        # The global breaker above still applies to everyone. That one exists to stop a
        # runaway loop draining the account overnight, and an admin can write a runaway loop
        # like anybody else.
        if (
            self._user_daily_budget_usd > 0
            and not _current_user_is_admin()
            and (uid := _current_user_scope()) is not None
        ):
            user_spent = await _spend_today(uid)
            if user_spent >= self._user_daily_budget_usd:
                logger.info(
                    "ai_user_budget_exceeded",
                    user_id=uid,
                    spent_usd=round(user_spent, 4),
                    budget_usd=self._user_daily_budget_usd,
                )
                raise UserBudgetExceededError(
                    f"You have used your ${self._user_daily_budget_usd:.2f} of AI practice "
                    "for today. Everything still works — you are on the standby model "
                    "until tomorrow.",
                    provider=self.provider_name,
                )

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_vision(self) -> bool:
        """
        Every Claude 3 model and later can look at an image, so this is unconditional.

        NOT read from a setting, unlike the OpenAI-compatible class. That one is shared by
        three providers whose configured model may be anything; this class only ever talks
        to Claude, and there is no Claude in the API that cannot see. A model old enough to
        fail this has been retired.
        """
        return True

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        """
        The answer as text deltas, through the SDK's own streaming helper.

        SAME PAYLOAD AS `complete`, deliberately — `_build_payload` is called here rather than
        rebuilt, so a streamed turn is the same request with the same model, the same budget
        and the same cached prefix. If those could differ, the streamed panel would sound
        subtly unlike the non-streamed one and nothing would say why.

        THINKING BLOCKS ARE NOT YIELDED. `text_stream` emits only the visible answer, which is
        what a caller rendering to a screen wants; a reasoning block arriving as if it were
        dialogue would put the model's deliberation in the interviewer's mouth.
        """
        await self._refuse_if_over_budget()
        payload, model, _max_tokens, _thinking, _effort = self._build_payload(request)
        log = logger.bind(provider=self.provider_name, model=model, streaming=True)
        try:
            async with self._client.messages.stream(**payload) as sdk_stream:
                async for delta in sdk_stream.text_stream:
                    yield StreamChunk(text=delta)
                # THE TERMINATOR, AND IT CARRIES THE USAGE. `get_final_message` returns the
                # assembled message with real input/output token counts, so a streamed call is
                # billed and recorded identically to a non-streamed one. Yielded only after
                # the loop completes, so a stream that died leaves no terminator and the
                # caller can tell.
                message = await sdk_stream.get_final_message()
                yield StreamChunk(final=self._to_response(message, model, log))
        except anthropic.APIStatusError as exc:
            body = str(exc.message)[:500]
            log.error("provider_stream_api_error", status_code=exc.status_code, body=body)
            raise ProviderError(
                f"anthropic API returned {exc.status_code}: {body}",
                provider=self.provider_name,
                status_code=exc.status_code,
                raw_error=body,
            ) from exc
        except anthropic.APIConnectionError as exc:
            # RAISED FROM INSIDE THE ITERATION, which is the whole point. A stream that dies
            # half way through has produced text that LOOKS like an answer, and the only thing
            # separating it from a finished one is that the iterator raised rather than
            # stopping. A caller that swallowed this would save half a panel turn as a whole
            # one. See api/v1/panel.py's streaming endpoint.
            log.error("provider_stream_network_error", error=str(exc))
            raise ProviderError(
                f"anthropic connection error: {exc}", provider=self.provider_name
            ) from exc

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        await self._refuse_if_over_budget()

        payload, model, max_tokens, thinking_enabled, effort = self._build_payload(request)

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
        cost = response.estimated_cost_usd or 0.0
        await _record_spend(cost)
        # And against the user who caused it, so their own allowance converges. The
        # contextvar is set by core/security.py on every authenticated request; it is
        # None for a background task or a script, and those spend against the global
        # breaker only — deliberately, because attributing anonymous spend to some
        # user would be worse than not attributing it.
        if (uid := _current_user_scope()) is not None:
            await _record_spend(cost, uid)
        return response

    # ─── Message Batches API ──────────────────────────────────────────────
    #
    # Half price, and answered whenever Anthropic gets to it rather than now. That trade is
    # only acceptable where nobody is waiting, which in this product is the report and
    # nothing else — the allowlist that enforces it lives in services/ai/batch.py, not here,
    # because a provider must not be the thing deciding which features exist.
    #
    # None of these four methods raise anything but ProviderError, same as `complete`.

    @property
    def supports_batching(self) -> bool:
        return True

    def build_batch_request(self, custom_id: str, request: ProviderRequest) -> dict:
        """
        One entry in a batch, from the same ProviderRequest `complete` would take.

        `custom_id` is how a result is matched back to the part that asked for it. The
        Batches API does NOT preserve order — results come back in whatever order they
        finished — so this id is the only link between a response and the questions it was
        supposed to grade. Getting it wrong would silently attach one candidate's
        per-question feedback to a different set of questions.
        """
        payload, _model, _max_tokens, _thinking, _effort = self._build_payload(request)
        return {"custom_id": custom_id, "params": payload}

    async def submit_batch(self, requests: list[dict]) -> str:
        """
        Hand a set of requests to the Batches API. Returns the provider's batch id.

        THE DAILY BREAKER IS CHECKED HERE TOO. A batch is billed like any other call — half
        price, but not free — and submitting one is the moment the money is committed, even
        though it is spent later. Skipping the check because the response has not arrived
        yet would leave a hole in the circuit breaker exactly the size of the most
        expensive feature in the product.
        """
        if not requests:
            raise ProviderError("cannot submit an empty batch", provider=self.provider_name)

        if self._daily_budget_usd > 0:
            spent = await _spend_today()
            if spent >= self._daily_budget_usd:
                logger.error(
                    "ai_daily_budget_exceeded_on_batch_submit",
                    spent_usd=round(spent, 4),
                    budget_usd=self._daily_budget_usd,
                )
                raise BudgetExceededError(
                    f"Daily AI budget of ${self._daily_budget_usd:.2f} reached "
                    f"(${spent:.4f} spent). The batch was not submitted.",
                    provider=self.provider_name,
                )

        try:
            # `type: ignore` because the SDK types `requests` as a TypedDict whose
            # `params` is the full MessageCreateParams. We build that payload in
            # _build_payload, which is dynamically shaped (`thinking` and `output_config`
            # vary by cost tier) and is already the exact dict `messages.create` accepts —
            # the same one, by construction. Narrowing it to the TypedDict here would mean
            # duplicating the builder for the batch path, which is precisely the drift
            # _build_payload exists to prevent.
            batch = await self._client.messages.batches.create(
                requests=requests  # type: ignore[arg-type]
            )
        except anthropic.APIStatusError as exc:
            body = str(exc.message)[:500]
            logger.error(
                "anthropic_batch_submit_failed",
                status_code=exc.status_code,
                body=body,
                parts=len(requests),
            )
            raise ProviderError(
                f"anthropic batch submit returned {exc.status_code}: {body}",
                provider=self.provider_name,
                status_code=exc.status_code,
                raw_error=body,
            ) from exc
        except anthropic.APIConnectionError as exc:
            logger.error("anthropic_batch_submit_network_error", error=str(exc))
            raise ProviderError(
                f"anthropic batch submit connection error: {exc}",
                provider=self.provider_name,
            ) from exc

        logger.info(
            "anthropic_batch_submitted",
            batch_id=batch.id,
            parts=len(requests),
            model=self._model,
        )
        return batch.id

    async def retrieve_batch(self, batch_id: str) -> tuple[str, dict[str, int]]:
        """
        (processing_status, request_counts) for a submitted batch.

        `processing_status` is Anthropic's own vocabulary — "in_progress", "canceling",
        "ended" — and is deliberately NOT translated here. The state machine that reads it
        lives in services/report/batch_job.py and is the one place that decides what a
        status means; mapping it twice is how the two would come to disagree.
        """
        try:
            batch = await self._client.messages.batches.retrieve(batch_id)
        except anthropic.APIStatusError as exc:
            body = str(exc.message)[:500]
            raise ProviderError(
                f"anthropic batch retrieve returned {exc.status_code}: {body}",
                provider=self.provider_name,
                status_code=exc.status_code,
                raw_error=body,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(
                f"anthropic batch retrieve connection error: {exc}",
                provider=self.provider_name,
            ) from exc

        counts = getattr(batch, "request_counts", None)
        return str(batch.processing_status), {
            "processing": getattr(counts, "processing", 0) or 0,
            "succeeded": getattr(counts, "succeeded", 0) or 0,
            "errored": getattr(counts, "errored", 0) or 0,
            "canceled": getattr(counts, "canceled", 0) or 0,
            "expired": getattr(counts, "expired", 0) or 0,
        }

    async def batch_results(self, batch_id: str) -> dict[str, ProviderResponse | str]:
        """
        Every finished part of an ended batch, keyed by the custom_id that asked for it.

        A part that succeeded maps to a ProviderResponse costed at the batch rate. A part
        that errored, expired or was cancelled maps to a STRING saying which — not to an
        exception and not to None. Per-part failure is an ordinary outcome here rather
        than an error: the report is already built to survive losing some of its analysis
        batches, so one dead part must not take the ones that worked down with it.
        """
        out: dict[str, ProviderResponse | str] = {}
        log = logger.bind(provider=self.provider_name, batch_id=batch_id)
        try:
            async for entry in await self._client.messages.batches.results(batch_id):
                custom_id = str(getattr(entry, "custom_id", "") or "")
                if not custom_id:
                    continue
                result = getattr(entry, "result", None)
                kind = str(getattr(result, "type", "") or "unknown")
                message = getattr(result, "message", None)
                if kind != "succeeded" or message is None:
                    # "errored" | "expired" | "canceled". Recorded rather than raised:
                    # see the docstring.
                    log.warning("anthropic_batch_part_failed", custom_id=custom_id, type=kind)
                    out[custom_id] = kind
                    continue
                try:
                    out[custom_id] = self._to_response(
                        message,
                        message.model,
                        log.bind(custom_id=custom_id),
                        price_multiplier=_BATCH_PRICE_MULTIPLIER,
                    )
                except ProviderError as exc:
                    # A refusal comes back as a successful batch entry whose message has
                    # stop_reason="refusal". _to_response raises on that, and it is one
                    # part's problem, not the batch's.
                    log.warning(
                        "anthropic_batch_part_refused", custom_id=custom_id, error=str(exc)
                    )
                    out[custom_id] = "refused"
        except anthropic.APIStatusError as exc:
            body = str(exc.message)[:500]
            raise ProviderError(
                f"anthropic batch results returned {exc.status_code}: {body}",
                provider=self.provider_name,
                status_code=exc.status_code,
                raw_error=body,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(
                f"anthropic batch results connection error: {exc}",
                provider=self.provider_name,
            ) from exc

        # THE SPEND IS RECORDED HERE, WHEN IT IS KNOWN, not at submit time when it is not.
        # Against the global breaker only: results are collected by a poll that may belong
        # to a different request, or to no user's request at all, and attributing a
        # batch's cost to whoever happened to poll for it would be worse than not
        # attributing it. The per-user allowance is charged by services/billing/credits.py
        # when the report is started, which is the honest place for it.
        billed = sum(
            r.estimated_cost_usd or 0.0 for r in out.values() if isinstance(r, ProviderResponse)
        )
        if billed:
            await _record_spend(billed)
            log.info(
                "anthropic_batch_spend",
                parts=len(out),
                estimated_cost_usd=round(billed, 6),
                discount_multiplier=_BATCH_PRICE_MULTIPLIER,
            )
        return out

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
                # IMAGES ON A SYSTEM MESSAGE ARE DROPPED, LOUDLY. Claude's `system`
                # parameter takes text blocks only, so there is nowhere to put them. No
                # call site builds one; a future one that does gets a warning rather than
                # a score computed from evidence that was silently discarded.
                if msg.images:
                    logger.warning(
                        "anthropic_dropped_system_images",
                        count=len(msg.images),
                        reason="Claude's system parameter accepts text blocks only",
                    )
                system_parts.append(msg.content)
            else:
                turns.append({"role": msg.role, "content": _turn_content(msg)})

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
        # Both must agree: the CALL SITE declares its system block is stable, and the
        # deployment has not switched caching off. Either alone is not enough — a
        # global flag would bill a 1.25x write on every call whose prompt is not
        # static, which is the trap the setting was disabled to avoid.
        if request.cache_system and self._prompt_caching:
            # Sonnet 5 only caches prefixes >= 1024 tokens. Shorter prompts
            # silently don't cache (no error, no charge) — verify with the
            # cache_read_input_tokens we log below.
            block["cache_control"] = {"type": "ephemeral"}
        return [block], turns

    def _to_response(
        self,
        message: anthropic.types.Message,
        model: str,
        log: structlog.BoundLogger,
        *,
        price_multiplier: float = 1.0,
    ) -> ProviderResponse:
        """
        Normalize a Claude Message into ProviderResponse.

        `price_multiplier` is 0.5 for a message answered through the Batches API and 1.0
        otherwise. It is a parameter rather than a separate cost function because the
        ledger and the daily spend cap must see ONE cost model: a batched report that
        reported its full price would make the batch look worthless in `ai_usage`, and one
        that reported nothing would make the breaker stop counting the most expensive
        feature in the product.
        """
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
            block.text for block in message.content if isinstance(block, TextBlock)
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
            (
                uncached_in * in_price
                + cache_write * in_price * 1.25
                + cached * in_price * 0.10
                + out * out_price
            )
            * price_multiplier
            / 1_000_000
        )

        log.info(
            "provider_request_complete",
            stop_reason=message.stop_reason,
            batched=price_multiplier != 1.0,
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
