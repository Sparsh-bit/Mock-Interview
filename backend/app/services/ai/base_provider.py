"""
AI Provider Abstraction Layer — base_provider.py

Defines the contract that all AI provider implementations must satisfy.
No service, endpoint, or orchestrator should ever import a concrete provider
class directly. All AI access flows through provider_factory.get_ai_provider().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


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
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32_768)
    #: When True, instructs the provider to return valid JSON.
    #: Providers that support a native JSON mode will enable it;
    #: others receive a prompt-level instruction.
    json_mode: bool = False
    #: Optionally override the configured model for a single request.
    model_override: str | None = None


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

    # ─── Lifecycle ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release HTTP connections and other resources. Override if needed."""

    async def __aenter__(self) -> "BaseAIProvider":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
