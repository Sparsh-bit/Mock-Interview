"""
AI Provider Abstraction Layer — base_provider.py

Defines the contract that all AI provider implementations must satisfy.
No service, endpoint, or orchestrator should ever import a concrete provider
class directly. All AI access flows through provider_factory.get_ai_provider().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ─── Cost tiers ───────────────────────────────────────────────────────────────


class CostTier(StrEnum):
    """
    How much reasoning a call is worth paying for.

    Deliberately provider-agnostic: it describes the *task*, not any vendor's
    knobs. Providers that bill for reasoning (Anthropic's thinking + effort)
    map these to real parameters; providers without the concept ignore them.

    Output tokens cost ~5x input, and reasoning tokens are billed as output —
    so picking the right tier per call site is the single biggest lever on
    spend. Choose by what the task actually needs:

    CHEAP    — mechanical extraction/scoring against an explicit rubric where
               the prompt already states the criteria (answer scoring,
               communication + GD evaluation). No reasoning purchased.
    BALANCED — generation that needs to be good but not deliberated
               (interview questions, quizzes, cross-questions, GD turns).
    DEEP     — genuine multi-step reasoning over a long input, where a wrong
               answer wastes the whole session (the final hire/no-hire report).
    """

    CHEAP = "cheap"
    BALANCED = "balanced"
    DEEP = "deep"


# ─── Request / Response value objects ────────────────────────────────────────


class ProviderMessage(BaseModel):
    """A single message in a conversation."""

    role: str  # "system" | "user" | "assistant"
    content: str

    model_config = {"frozen": True}


class ProviderRequest(BaseModel):
    """
    Provider-agnostic completion request.

    All AI services in this application accept this shape and pass it to
    the provider layer. Provider implementations translate it to their
    native API format.
    """

    messages: list[ProviderMessage]
    #: Sampling temperature. Honoured by OpenAI-compatible providers; the
    #: Anthropic provider DROPS it, because Claude Sonnet 5 and the Opus 4.7+
    #: family reject non-default sampling params with a 400. Steer Claude via
    #: the prompt (and `cost_tier`) instead.
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32_768)
    #: How much reasoning this call is worth paying for. See CostTier.
    cost_tier: CostTier = CostTier.BALANCED
    #: When True, instructs the provider to return valid JSON.
    #: Providers that support a native JSON mode will enable it;
    #: others receive a prompt-level instruction.
    json_mode: bool = False
    #: This call's system block is byte-identical across requests, so marking it
    #: cacheable will produce cache READS and not just writes.
    #:
    #: Opt-in per call, deliberately. A cache write bills at 1.25x input, so switching
    #: caching on for a call whose system block carries per-request substitutions costs
    #: 25% extra every time and never reads — which is exactly why the provider-level
    #: flag was left off. Only a call site that has made its system prompt static may
    #: set this, and there is a test asserting the prompt really is static.
    cache_system: bool = False
    #: Optionally override the configured model for a single request.
    model_override: str | None = None
    #: WHICH FEATURE THIS CALL IS, verbatim from the `context=` at the generate_structured
    #: call site — "interview_panel_turn", "report_analysis", "gd_evaluation".
    #:
    #: Carried so a provider can act on a POLICY that is keyed by feature without any
    #: caller having to know it exists. Today that is model routing: see
    #: services/ai/model_routing.py, which decides that panel dialogue may run on a smaller
    #: model while the two CHEAP calls that SCORE a candidate may not. A cost tier alone
    #: cannot express that — both are CHEAP.
    #:
    #: None when the caller declared nothing, and every policy reading it must treat that as
    #: "not on any allowlist". A provider must still not contain the policy itself; this is
    #: the fact the policy needs, not the decision.
    feature: str | None = None


class ProviderResponse(BaseModel):
    """
    Provider-agnostic completion response.

    All provider implementations normalize their API response to this shape
    before returning to the caller. This insulates business logic from
    provider-specific response structures.
    """

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str  # "stop" | "length" | "content_filter" | etc.
    #: Input tokens served from the prompt cache at ~0.1x price. Providers
    #: without prompt caching leave this at 0.
    cached_input_tokens: int = 0
    #: Input tokens written to the prompt cache at ~1.25x price (paid once,
    #: then read cheaply for the cache lifetime).
    cache_write_tokens: int = 0
    #: Estimated USD cost of this single call, when the provider knows its
    #: own price sheet. None when unpriced (e.g. free-tier providers).
    estimated_cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed by this request."""
        return self.prompt_tokens + self.completion_tokens

    model_config = {"frozen": True}


# ─── Provider error ───────────────────────────────────────────────────────────


class ProviderError(Exception):
    """
    Raised when an AI provider API call fails.

    Callers must catch this and convert it to a controlled application-level
    error. Never let ProviderError propagate to interview session logic —
    the interview engine must never crash due to an AI provider failure.
    """

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int | None = None,
        raw_error: Any = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.raw_error = raw_error

    def is_rate_limit(self) -> bool:
        return self.status_code == 429

    def is_auth_error(self) -> bool:
        return self.status_code in {401, 403}

    def is_server_error(self) -> bool:
        return self.status_code is not None and self.status_code >= 500


# ─── Abstract base ────────────────────────────────────────────────────────────


class BaseAIProvider(ABC):
    """
    Abstract base class for all AI provider implementations.

    Architectural rules:
    - Implementations MUST NOT contain business logic of any kind.
    - Implementations MUST normalize all responses to ProviderResponse.
    - Implementations MUST raise ProviderError — never the raw SDK exception.
    - Implementations MUST be stateless between requests (safe for reuse).
    - No service, orchestrator, or API handler may import a concrete
      provider class. Always use provider_factory.get_ai_provider().

    Swapping providers (e.g., GLM → GPT-4) requires only a config change:
        AI_PROVIDER=openai   # in .env
    No application code changes required.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable identifier, e.g. 'glm', 'openai', 'anthropic'."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The active model, e.g. 'glm-4-flash', 'gpt-4o', 'claude-3-5-sonnet'."""

    @abstractmethod
    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        """
        Send a completion request to the provider.

        Raises:
            ProviderError: On any API failure (network, auth, rate limit, etc.)
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verify the provider is reachable and the API key is valid.
        Must not raise — return False on failure.
        """

    # ─── Optional: asynchronous batch submission ──────────────────────────

    @property
    def supports_batching(self) -> bool:
        """
        Can this provider take a set of requests now and answer them later, cheaply?

        FALSE HERE ON PURPOSE, and it is not a stub. Most providers in this chain have no
        such API, and a caller must be able to ask rather than guess — the alternative is
        `isinstance(provider, AnthropicProvider)` at the call site, which is exactly the
        coupling this base class exists to forbid.

        A provider that answers True must implement submit_batch / retrieve_batch /
        batch_results. Nothing in this codebase may batch a call that a person is waiting
        on: see services/ai/batch.py for the feature allowlist that enforces it.
        """
        return False

    # ─── Lifecycle ────────────────────────────────────────────────────────

    async def close(self) -> None:  # noqa: B027
        """
        Release HTTP connections and other resources.

        Intentionally a concrete no-op rather than abstract: a provider with
        nothing to release (a stub, a local model, a test double) should not be
        forced to write an empty override just to be instantiable. Providers that
        hold a client — every real one — override it.
        """

    async def __aenter__(self) -> BaseAIProvider:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
