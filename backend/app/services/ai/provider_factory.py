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


def _lazy_register() -> None:
    """
    Register all built-in providers.
    Called once on first use of get_ai_provider().
    Imports are deferred so unused providers don't load their dependencies.
    """
    global _PROVIDER_REGISTRY  # noqa: PLW0603

    from .glm_provider import GLMProvider  # noqa: PLC0415

    _PROVIDER_REGISTRY = {
        "glm": GLMProvider,
        # Future providers — implement the class, uncomment the line, done:
        # "openai": OpenAIProvider,
        # "anthropic": AnthropicProvider,
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
    FastAPI dependency — returns a configured AI provider instance.

    The provider is determined entirely by the AI_PROVIDER environment variable.
    No service or endpoint should import a concrete provider class.

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
    if not _PROVIDER_REGISTRY:
        _lazy_register()

    # Import here to avoid circular import at module level
    from app.core.config import settings  # noqa: PLC0415

    name = settings.AI_PROVIDER.lower().strip()

    if name not in _PROVIDER_REGISTRY:
        available = sorted(_PROVIDER_REGISTRY.keys())
        raise ValueError(
            f"Unknown AI provider '{name}'. "
            f"Available: {available}. "
            f"Check the AI_PROVIDER setting in your .env file."
        )

    provider_cls = _PROVIDER_REGISTRY[name]
    instance = _build_provider(name, provider_cls)

    logger.debug(
        "ai_provider_created",
        provider=name,
        model=instance.model_name,
    )

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
            )
        # case "openai":
        #     return cls(api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL)
        # case "anthropic":
        #     return cls(api_key=settings.ANTHROPIC_API_KEY, model=settings.ANTHROPIC_MODEL)
        case _:
            raise ValueError(
                f"Provider '{name}' is registered but has no build configuration. "
                f"Add a case to provider_factory._build_provider()."
            )
