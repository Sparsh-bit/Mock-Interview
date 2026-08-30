"""
Is the model provider actually reachable? — services/ai/reachability.py

WHY THIS IS NOT `BaseAIProvider.health_check()`, WHICH ALREADY EXISTS.

Both existing implementations of `health_check()` make a REAL COMPLETION CALL.
`AnthropicProvider` sends `messages.create(max_tokens=1)`; `OpenAICompatibleProvider`
goes through `self.complete()`, which is the whole billed path including the usage
ledger. They are appropriate for a manual "is my key working" probe and they are
completely wrong for a health endpoint:

  * docs/UPTIME.md has monitors hitting `/api/v1/health` every 3 minutes. That is
    ~480 completion calls a day, per provider, forever.
  * The GLM path writes to `ai_usage`, which is the ledger docs/AI-COST-MODEL.md and
    every pricing decision are derived from. Synthetic traffic in it does not just
    cost money, it corrupts the numbers the business runs on — the same reason
    docs/UPTIME.md says never to monitor a POST endpoint.
  * Completion endpoints have the tightest rate limits a provider offers, so the
    health check would compete with real interviews for them.

SO THIS ASKS A CHEAPER QUESTION: `GET {base_url}/models`. Every provider here
serves it, it runs no inference, it is billed at nothing, and it sits under a
separate and far more generous rate limit than completions. It still proves the two
things worth proving — that the network path out of this container works, and that
the API key is accepted — because it is an AUTHENTICATED endpoint. A plain TCP or
TLS probe would prove only the first, and "reachable with a dead key" is the outage
that looks healthiest.

WHAT IT DOES NOT PROVE, stated so nobody reads more into a green result: that the
specific MODEL is available, that quota remains, or that a completion would succeed.
Those cost money to establish.

DEGRADES TO "unknown", NEVER HANGS. A provider having a slow day must not make this
application's health endpoint slow — a monitor timing out on /health would report the
whole service down because a third party was sluggish. Every probe is wrapped in a
hard `asyncio.wait_for`, the whole set is bounded again, and anything that does not
answer in time is "unknown" rather than "unreachable": not knowing is a different
fact from knowing it is broken, and reporting the second would page somebody.

CACHED IN-PROCESS. Without a cache, `/health` becomes an amplifier — anything that
can hit it can make this container open connections to Anthropic as fast as it likes.
The TTL is longer than the monitor interval, so the ordinary case costs nothing at all.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

import httpx
import structlog

logger = structlog.get_logger(__name__)

Status = Literal["reachable", "unreachable", "unknown", "not_configured"]

#: Per-provider budget. Deliberately tight: this runs inside a request that a load
#: balancer is timing, and a provider that cannot answer in 2 seconds is a provider
#: whose answer we do not need right now.
PROBE_TIMEOUT_SECONDS = 2.0

#: Ceiling for the whole set, regardless of how many providers are in the chain.
#: Belt and braces over the per-probe timeout, because `asyncio.wait_for` around a
#: gather is the thing that holds when a probe fails to honour its own deadline.
TOTAL_TIMEOUT_SECONDS = 3.0

#: How long a result is reused. Longer than the 3-minute monitor interval in
#: docs/UPTIME.md, so scheduled monitoring costs one probe per interval at most and
#: a burst of requests costs nothing.
CACHE_TTL_SECONDS = 240.0

_cache: dict[str, Any] = {"at": 0.0, "result": None}


def _endpoint_for(base_url: str) -> str:
    """
    The model-list URL for an OpenAI-compatible base.

    Bases are configured with or without the `/v1` suffix depending on the vendor, so
    this appends `models` to whatever is there rather than assuming a shape. Guessing
    wrong produces a 404, which this treats as REACHABLE — see `_probe`.
    """
    return f"{base_url.rstrip('/')}/models"


async def _probe(name: str, url: str, headers: dict[str, str]) -> Status:
    """
    One provider. Never raises.

    ANY HTTP RESPONSE COUNTS AS REACHABLE, INCLUDING 404 AND 405, and that is
    deliberate rather than sloppy. The question is "can this container reach the
    provider and is its credential accepted", and a routed HTTP response answers the
    first conclusively. Only 401 and 403 are treated as a real failure, because those
    are the provider telling us the key is no longer good — which is an outage that a
    connectivity check alone would report as healthy.
    """
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers)
    except (TimeoutError, httpx.TimeoutException):
        logger.info("ai_provider_probe_timed_out", provider=name)
        return "unknown"
    except httpx.HTTPError as exc:
        # DNS failure, TLS failure, connection refused — the network path is broken.
        logger.warning("ai_provider_unreachable", provider=name, error=type(exc).__name__)
        return "unreachable"

    if response.status_code in (401, 403):
        logger.error(
            "ai_provider_rejected_our_credentials",
            provider=name,
            status_code=response.status_code,
            hint="the API key is missing, revoked or wrong; completions will fail",
        )
        return "unreachable"

    return "reachable"


def _targets() -> list[tuple[str, str, dict[str, str]]]:
    """
    (name, url, headers) for every provider in the configured chain.

    READS THE SAME SETTINGS THE REQUEST PATH READS, so the health endpoint reports on
    the providers this deployment would actually call — not on a list somebody wrote
    down once. A provider named in AI_PROVIDER with no key is reported
    `not_configured`, which is a more useful answer than a failed probe.
    """
    from app.core.config import settings  # noqa: PLC0415

    out: list[tuple[str, str, dict[str, str]]] = []
    seen: set[str] = set()

    for name in (settings.AI_PROVIDER, settings.AI_FALLBACK_PROVIDER):
        key = (name or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)

        if key == "anthropic":
            if not settings.ANTHROPIC_API_KEY:
                continue
            out.append(
                (
                    key,
                    "https://api.anthropic.com/v1/models",
                    {
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        # Required on every Anthropic request; without it the API
                        # answers 400 — still "reachable", but the log would be
                        # confusing to whoever reads it next.
                        "anthropic-version": "2023-06-01",
                    },
                )
            )
        elif key == "glm" and settings.GLM_API_KEY:
            out.append(
                (
                    key,
                    _endpoint_for(settings.GLM_BASE_URL),
                    {"Authorization": f"Bearer {settings.GLM_API_KEY}"},
                )
            )
        elif key == "nvidia" and settings.NVIDIA_API_KEY:
            out.append(
                (
                    key,
                    _endpoint_for(settings.NVIDIA_BASE_URL),
                    {"Authorization": f"Bearer {settings.NVIDIA_API_KEY}"},
                )
            )

    return out


async def check_provider_chain(*, use_cache: bool = True) -> dict[str, Status]:
    """
    Probe every configured provider. Never raises, never hangs.

    Returns a name -> status map. An empty map means nothing is configured, which the
    health endpoint reports as `not_configured` rather than as healthy — a deployment
    with no model provider is not a working deployment, and saying "ok" about it is
    the kind of green tick docs/UPTIME.md is mostly about.
    """
    now = time.monotonic()
    if use_cache and _cache["result"] is not None and now - _cache["at"] < CACHE_TTL_SECONDS:
        return dict(_cache["result"])

    targets = _targets()
    if not targets:
        result: dict[str, Status] = {}
    else:
        try:
            statuses = await asyncio.wait_for(
                asyncio.gather(
                    *(_probe(name, url, headers) for name, url, headers in targets),
                    # A probe that raises something unforeseen must not take the
                    # health endpoint down with it.
                    return_exceptions=True,
                ),
                timeout=TOTAL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            # The outer bound fired: report every provider as unknown rather than
            # letting the request hang. Not cached — see below.
            return dict.fromkeys((name for name, _, _ in targets), "unknown")

        result = {}
        for (name, _, _), status in zip(targets, statuses, strict=True):
            if isinstance(status, BaseException):
                logger.warning(
                    "ai_provider_probe_errored", provider=name, error=type(status).__name__
                )
                result[name] = "unknown"
            else:
                result[name] = status

    # ONLY A DEFINITE ANSWER IS CACHED. Caching "unknown" for four minutes would keep
    # reporting a stale non-answer long after the provider recovered, which is worse
    # than probing again.
    if all(status != "unknown" for status in result.values()):
        _cache["at"] = now
        _cache["result"] = dict(result)

    return result


def reset_cache() -> None:
    """For tests, and for anything that needs a fresh answer now."""
    _cache["at"] = 0.0
    _cache["result"] = None
