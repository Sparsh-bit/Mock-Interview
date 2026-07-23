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

# ─── Application singleton ────────────────────────────────────────────────────
# Created once in the FastAPI lifespan startup (initialize_ai_provider()) and
# closed in shutdown (close_ai_provider()) — see app/main.py. This prevents a
# new httpx.AsyncClient connection pool from being leaked on every request.
_provider_instance: BaseAIProvider | None = None


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
    global _provider_instance  # noqa: PLW0603

    if _provider_instance is not None:
        return _provider_instance

    # Fallback for callers that run before lifespan startup (e.g. tests) —
    # lazily create and cache the singleton rather than raising, but log it
    # so an accidental missing initialize_ai_provider() call is visible.
    logger.warning(
        "ai_provider_singleton_lazily_created",
        reason="get_ai_provider() called before initialize_ai_provider() lifespan startup",
    )
    _provider_instance = _create_provider()
    return _provider_instance


def initialize_ai_provider() -> BaseAIProvider:
    """
    Create and cache the application-scoped AI provider singleton.

    Call once in FastAPI lifespan startup:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            initialize_ai_provider()
            yield
            await close_ai_provider()
    """
    global _provider_instance  # noqa: PLW0603

    _provider_instance = _create_provider()
    logger.info(
        "ai_provider_initialized",
        provider=_provider_instance.provider_name,
        model=_provider_instance.model_name,
    )
    return _provider_instance


async def close_ai_provider() -> None:
    """
    Release the singleton AI provider's resources (e.g. httpx connection pool).

    Call once in FastAPI lifespan shutdown, after initialize_ai_provider()
    was called at startup.
    """
    global _provider_instance  # noqa: PLW0603

    if _provider_instance is not None:
        await _provider_instance.close()
        logger.info("ai_provider_closed", provider=_provider_instance.provider_name)
        _provider_instance = None


def _create_provider() -> BaseAIProvider:
    """Build a new provider instance from the configured AI_PROVIDER setting."""
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
