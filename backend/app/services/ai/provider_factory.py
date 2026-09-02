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

from collections.abc import Callable

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
        # Groq's endpoint is OpenAI-shaped, so it reuses the same class. What makes it
        # different is the ACCOUNT, not the transport: it is a free tier, and
        # services/ai/burst_rung.py restricts which calls may reach it.
        "groq": OpenAICompatibleProvider,
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

    # ── A PRIMARY THAT CANNOT BE BUILT MUST NOT TAKE THE APP DOWN ────────────────────────
    #
    # This was `[_create_provider(settings.AI_PROVIDER)]` with nothing around it, so a missing
    # or rejected API key for the primary raised inside lifespan startup and the whole service
    # refused to boot — every endpoint, including the ones that need no AI at all: login, the
    # dashboard, the question banks, billing.
    #
    # That is the wrong failure. A configured fallback with a valid key can serve every AI
    # feature perfectly well, and an app that is up on its second-choice model is worth
    # immeasurably more than one that is down on its first. Logged as an ERROR, and the chain
    # is reported on /admin/ai-usage, so running on the fallback is loud rather than silent.
    #
    # It still fails hard when there is NOTHING to run on — see the raise below. That is a real
    # misconfiguration and booting into it would only move the failure to every request.
    chain: list[BaseAIProvider] = []
    primary_name = settings.AI_PROVIDER.lower().strip()
    try:
        chain.append(_create_provider(primary_name))
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ai_primary_provider_unavailable",
            provider=primary_name,
            error=str(exc),
            detail=(
                "the PRIMARY provider could not be created — almost always a missing or "
                "rejected API key. Falling through to AI_FALLBACK_PROVIDER; every AI feature "
                "is now running on the second choice"
            ),
        )

    fallback_name = (settings.AI_FALLBACK_PROVIDER or "").lower().strip()
    if fallback_name and fallback_name != primary_name:
        try:
            chain.append(_create_provider(fallback_name))
        except Exception as exc:  # noqa: BLE001
            # ERROR, NOT WARNING, AND THE WORDING IS DELIBERATE.
            #
            # A fallback that cannot be constructed — almost always a missing API key in the
            # environment — leaves the chain one provider long. Nothing breaks while the
            # primary is healthy, so this is invisible until the moment it matters: the primary
            # hits its daily spend cap or a rate limit, there is nothing behind it, and EVERY
            # AI feature fails at once. Candidates see "the model was unreachable" on their
            # report, which is true and says nothing about the cause.
            #
            # It was a warning, which in practice means nobody reads it. The chain is also
            # reported on /admin/ai-usage so the state is visible without reading logs at all.
            logger.error(
                "ai_fallback_provider_unavailable",
                provider=fallback_name,
                error=str(exc),
                detail=(
                    "the provider chain has NO fallback: if the primary refuses or hits its "
                    "daily budget, every AI feature will fail until this is fixed"
                ),
            )

    # ── THE BURST RUNG, STRICTLY LAST ────────────────────────────────────────────────────
    #
    # A free tier appended behind both paid providers, reachable only from calls that pass
    # the two gates in services/ai/burst_rung.py. It is a rung, not headroom: the free plan
    # is measured in single-digit thousands of tokens a minute, which is less than one live
    # GD round. See that module for the numbers.
    #
    # Failing to construct it is a WARNING and not an error, unlike the fallback above. The
    # difference is what its absence costs: a missing fallback means the next spend cap takes
    # every AI feature down, while a missing burst rung means two presentation-only features
    # degrade to their existing no-AI path during an outage that is already happening.
    burst_name = (settings.AI_BURST_PROVIDER or "").lower().strip()
    if burst_name and burst_name not in {primary_name, fallback_name}:
        try:
            chain.append(_create_provider(burst_name))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ai_burst_provider_unavailable",
                provider=burst_name,
                error=str(exc),
                detail=(
                    "the optional free-tier rung was not added — almost always an unset key. "
                    "Nothing breaks: it only ever serves panel dialogue, and only when both "
                    "paid providers have already refused"
                ),
            )

    if not chain:
        # NOTHING TO RUN ON. Distinct from the degraded case above: there is no provider at
        # all, so booting would only turn one startup error into a failure on every request,
        # with a different and less informative message each time.
        raise RuntimeError(
            f"No AI provider could be created. AI_PROVIDER={primary_name!r} and "
            f"AI_FALLBACK_PROVIDER={fallback_name!r} both failed to construct — check that "
            "the API key for at least one of them is set in the environment."
        )

    # A CHAIN OF NOTHING BUT THE BURST RUNG IS NOT A CHAIN, and this is the case that would
    # otherwise boot looking healthy. If both paid providers fail to construct and the free
    # one succeeds, `chain` is non-empty, the guard above passes, and the service starts —
    # then every report, every score and every cross-question fails, because burst_rung
    # correctly refuses to serve them from a free tier. The failure would arrive per-request,
    # in the middle of candidates' sessions, instead of once at startup where it belongs.
    from .burst_rung import is_burst_rung  # noqa: PLC0415

    if all(is_burst_rung(p) for p in chain):
        raise RuntimeError(
            f"The only AI provider that could be created is the free-tier burst rung "
            f"({burst_name!r}), which is restricted to panel dialogue and cannot serve "
            f"reports, scoring or question generation. AI_PROVIDER={primary_name!r} and "
            f"AI_FALLBACK_PROVIDER={fallback_name!r} both failed to construct — check that "
            "the API key for at least one of them is set in the environment."
        )

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


def _build_provider(name: str, cls: Callable[..., BaseAIProvider]) -> BaseAIProvider:
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
                supports_vision=settings.GLM_SUPPORTS_VISION,
            )
        case "nvidia":
            return cls(
                api_key=settings.NVIDIA_API_KEY,
                model=settings.NVIDIA_MODEL,
                base_url=settings.NVIDIA_BASE_URL,
                provider_name="nvidia",
                supports_vision=settings.NVIDIA_SUPPORTS_VISION,
                # Large reasoning models (e.g. nemotron-3-ultra) can take
                # noticeably longer than GLM's flash-tier models.
                read_timeout=180.0,
            )
        case "groq":
            return cls(
                api_key=settings.GROQ_API_KEY,
                model=settings.GROQ_MODEL,
                base_url=settings.GROQ_BASE_URL,
                provider_name="groq",
                supports_vision=settings.GROQ_SUPPORTS_VISION,
                # Short. The rung exists because the paid providers are already failing, so
                # a call has usually spent its retries by the time it arrives — waiting a
                # further two minutes on a free tier would hold a worker past the point the
                # caller's own budget gives up. Groq is fast; if it is not, skip it.
                read_timeout=30.0,
            )
        case "anthropic":
            return cls(
                api_key=settings.ANTHROPIC_API_KEY,
                model=settings.ANTHROPIC_MODEL,
                provider_name="anthropic",
                # What a CHEAP call on an allowlisted feature runs on instead — see
                # services/ai/model_routing.py for which features, and why it is not all of
                # them. Empty switches the routing off entirely.
                cheap_model=settings.ANTHROPIC_CHEAP_MODEL,
                # Cost guards — see anthropic_provider.py.
                prompt_caching=settings.ANTHROPIC_PROMPT_CACHING,
                max_output_tokens=settings.ANTHROPIC_MAX_OUTPUT_TOKENS,
                daily_budget_usd=settings.AI_DAILY_BUDGET_USD,
                user_daily_budget_usd=settings.AI_USER_DAILY_BUDGET_USD,
            )
        case _:
            raise ValueError(
                f"Provider '{name}' is registered but has no build configuration. "
                f"Add a case to provider_factory._build_provider()."
            )
