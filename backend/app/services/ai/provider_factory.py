"""
Provider Factory — provider_factory.py

The single point of AI provider instantiation for the entire application.

Architecture:
  - A registry maps provider name strings to provider classes.
  - get_ai_provider() is a FastAPI dependency that returns the configured provider.
  - No service, orchestrator, or endpoint may instantiate a provider directly.
  - Swapping providers requires only a config change: AI_PROVIDER=openai

Adding a new provider:
  1. Create backend/app/services/ai/openai_provider.py implementing BaseAIProvider.
  2. Add it to _PROVIDER_REGISTRY in _lazy_register().
  3. Add its config section to _build_provider().
  4. Set AI_PROVIDER=openai in .env.
  No other files need to change.
"""

from __future__ import annotations

import structlog

from .base_provider import BaseAIProvider

logger = structlog.get_logger(__name__)

# The registry — populated lazily to defer heavy imports until needed
_PROVIDER_REGISTRY: dict[str, type[BaseAIProvider]] = {}

# ─── Application singletons ───────────────────────────────────────────────────
# An ordered list of providers: [primary, fallback?]. Created once in the
# FastAPI lifespan startup (initialize_ai_provider()) and closed in shutdown
# (close_ai_provider()) — see app/main.py. Holding them process-wide avoids
# leaking a new httpx.AsyncClient connection pool on every request; the ordered
# list lets AI calls fall back to the second provider when the first fails
# (see services/ai/generate.py).
_providers: list[BaseAIProvider] = []


def _lazy_register() -> None:
    """
    Register all built-in providers.
    Called once on first use of get_ai_provider().
    Imports are deferred so unused providers don't load their dependencies.
    """
    global _PROVIDER_REGISTRY  # noqa: PLW0603

    from .anthropic_provider import AnthropicProvider  # noqa: PLC0415
    from .glm_provider import OpenAICompatibleProvider  # noqa: PLC0415

    _PROVIDER_REGISTRY = {
        "glm": OpenAICompatibleProvider,
        "nvidia": OpenAICompatibleProvider,
        "anthropic": AnthropicProvider,
        # Future providers — implement the class, uncomment the line, done:
        # "openai": OpenAIProvider,
        # "gemini": GeminiProvider,
        # "local": LocalOllamaProvider,
    }


def register_provider(name: str, cls: type[BaseAIProvider]) -> None:
    """
    Register a custom AI provider at runtime.

    Call this once at application startup (e.g., in your FastAPI lifespan)
    before any AI endpoints are used.

    Example:
        from app.services.ai.provider_factory import register_provider
        from mypackage.providers import MyCustomProvider

        register_provider("custom", MyCustomProvider)
        # Then set AI_PROVIDER=custom in .env
    """
    if not _PROVIDER_REGISTRY:
        _lazy_register()
    _PROVIDER_REGISTRY[name] = cls
    logger.info("ai_provider_registered", name=name, class_name=cls.__name__)


def get_ai_provider() -> BaseAIProvider:
    """
    FastAPI dependency — returns the application-scoped AI provider singleton.

    The provider is determined entirely by the AI_PROVIDER environment variable.
    No service or endpoint should import a concrete provider class.

    The instance is created once (in the FastAPI lifespan startup, via
    initialize_ai_provider()) and reused for the lifetime of the process —
    this avoids leaking a new httpx.AsyncClient connection pool on every call.

    Usage in endpoints:
        from fastapi import Depends
        from app.services.ai.base_provider import BaseAIProvider
        from app.services.ai.provider_factory import get_ai_provider

        @router.post("/evaluate")
        async def evaluate_answer(
            provider: BaseAIProvider = Depends(get_ai_provider),
        ):
            response = await provider.complete(request)

    Usage in service classes:
        class EvaluationService:
            def __init__(
                self,
                provider: BaseAIProvider = Depends(get_ai_provider),
                parser: ResponseParser = Depends(get_response_parser),
            ):
                self._provider = provider
                self._parser = parser
    """
    return get_ai_providers()[0]


def get_ai_providers() -> list[BaseAIProvider]:
    """
    Return the ordered provider chain [primary, fallback?].

    AI calls try the primary first and fall back to the next on failure
    (see services/ai/generate.py). Lazily built if called before lifespan
    startup (e.g. in tests), logged so a missing init is visible.
    """
    global _providers  # noqa: PLW0603

    if _providers:
        return _providers

    logger.warning(
        "ai_providers_lazily_created",
        reason="get_ai_providers() called before initialize_ai_provider() lifespan startup",
    )
    _providers = _build_provider_chain()
    return _providers


def initialize_ai_provider() -> BaseAIProvider:
    """
    Create and cache the application-scoped AI provider chain (primary +
    optional fallback).

    Call once in FastAPI lifespan startup:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            initialize_ai_provider()
            yield
            await close_ai_provider()
    """
    global _providers  # noqa: PLW0603

    _providers = _build_provider_chain()
    logger.info(
        "ai_providers_initialized",
        chain=[p.provider_name for p in _providers],
        primary_model=_providers[0].model_name if _providers else None,
    )
    return _providers[0]


async def close_ai_provider() -> None:
    """
    Release every provider's resources (e.g. httpx connection pools).
    Call once in FastAPI lifespan shutdown.
    """
    global _providers  # noqa: PLW0603

    for p in _providers:
        try:
            await p.close()
            logger.info("ai_provider_closed", provider=p.provider_name)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            logger.warning("ai_provider_close_failed", provider=p.provider_name)
    _providers = []


def _build_provider_chain() -> list[BaseAIProvider]:
    """
    Build [primary] + [fallback] from settings. The fallback is included only
    when configured, distinct from the primary, and successfully constructible
    (e.g. its API key is set) — a missing/broken fallback never blocks startup.
    """
    from app.core.config import settings  # noqa: PLC0415

    chain: list[BaseAIProvider] = [_create_provider(settings.AI_PROVIDER)]

    fallback_name = (settings.AI_FALLBACK_PROVIDER or "").lower().strip()
    primary_name = settings.AI_PROVIDER.lower().strip()
    if fallback_name and fallback_name != primary_name:
        try:
            chain.append(_create_provider(fallback_name))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_fallback_provider_unavailable", provider=fallback_name, error=str(exc))

    return chain


def _create_provider(provider_name: str) -> BaseAIProvider:
    """Build a single provider instance by name."""
    if not _PROVIDER_REGISTRY:
        _lazy_register()

    name = provider_name.lower().strip()

    if name not in _PROVIDER_REGISTRY:
        available = sorted(_PROVIDER_REGISTRY.keys())
        raise ValueError(
            f"Unknown AI provider '{name}'. Available: {available}. "
            f"Check the AI_PROVIDER / AI_FALLBACK_PROVIDER settings in your .env file."
        )

    provider_cls = _PROVIDER_REGISTRY[name]
    instance = _build_provider(name, provider_cls)
    logger.debug("ai_provider_created", provider=name, model=instance.model_name)
    return instance


def _build_provider(name: str, cls: type[BaseAIProvider]) -> BaseAIProvider:
    """
    Construct a provider instance with config values from settings.

    Each provider section reads only the env vars it needs.
    Adding config for a new provider is the ONLY change needed here.
    """
    from app.core.config import settings  # noqa: PLC0415

    match name:
        case "glm":
            return cls(
                api_key=settings.GLM_API_KEY,
                model=settings.GLM_MODEL,
                base_url=settings.GLM_BASE_URL,
                provider_name="glm",
            )
        case "nvidia":
            return cls(
                api_key=settings.NVIDIA_API_KEY,
                model=settings.NVIDIA_MODEL,
                base_url=settings.NVIDIA_BASE_URL,
                provider_name="nvidia",
                # Large reasoning models (e.g. nemotron-3-ultra) can take
                # noticeably longer than GLM's flash-tier models.
                read_timeout=180.0,
            )
        case "anthropic":
            return cls(
                api_key=settings.ANTHROPIC_API_KEY,
                model=settings.ANTHROPIC_MODEL,
                provider_name="anthropic",
                # Cost guards — see anthropic_provider.py.
                prompt_caching=settings.ANTHROPIC_PROMPT_CACHING,
                max_output_tokens=settings.ANTHROPIC_MAX_OUTPUT_TOKENS,
            )
        # case "openai":
        #     return cls(api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL)
        case _:
            raise ValueError(
                f"Provider '{name}' is registered but has no build configuration. "
                f"Add a case to provider_factory._build_provider()."
            )
