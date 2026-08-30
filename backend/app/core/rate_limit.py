"""
Rate limiting — core/rate_limit.py

Redis-backed fixed-window rate limiting using INCR + EXPIRE.

Each limiter is a FastAPI dependency factory: call it with a limit and a
window (in seconds) plus a key-builder to get a dependency that raises
HTTP 429 once the caller has exceeded `limit` requests within the current
window. Windows are fixed (not sliding) — simple and cheap, consistent
with the rest of this codebase's "keep it simple" Redis usage.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog
from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.security import CurrentUser
from app.db.redis import get_redis

logger = structlog.get_logger(__name__)


def rate_limiter(
    *,
    limit: int,
    window_seconds: int,
    key_builder: Callable[[str], str],
    action: str,
) -> Callable:
    """
    Build a FastAPI dependency enforcing a fixed-window rate limit.

    Args:
        limit: Max requests allowed per window.
        window_seconds: Fixed window size, in seconds.
        key_builder: Given the user id (str), returns the Redis key to
            count against (e.g. CacheKeys.rate_limit_interview).
        action: Human-readable label used in the 429 detail message.

    Fails open on Redis errors — a rate limiter outage should not take
    down the interview flow.
    """

    async def _check(
        current_user: CurrentUser,
        redis: Redis = Depends(get_redis),
    ) -> None:
        await enforce_limit(
            redis,
            key=key_builder(str(current_user.user_id)),
            limit=limit,
            window_seconds=window_seconds,
            action=action,
        )

    return _check


def ip_rate_limiter(
    *,
    limit: int,
    window_seconds: int,
    key_builder: Callable[[str], str],
    action: str,
) -> Callable:
    """
    A limiter for a route with NO authenticated caller.

    `rate_limiter()` above depends on `CurrentUser`, so it cannot be applied to login-
    adjacent or public routes — which is why account provisioning and the public share link
    had no limit of any kind. This keys on `core.client_ip.client_ip` instead: a validated
    address, taken from a proxy header only when a trusted proxy is configured to have
    written it, and never from a header a caller can simply assert. Read that module before
    changing this; `docs/COMPLIANCE.md` records a standing decision against IP keying and
    the reasoning there is right for authenticated routes.

    Fails OPEN on a Redis error, exactly like `rate_limiter`. That consistency matters more
    than it looks: an IP limiter that failed CLOSED would lock every candidate out of
    signing in during a Redis blip, which is a worse outage than the abuse it prevents.
    """

    async def _check(
        request: Request,
        redis: Redis = Depends(get_redis),
    ) -> None:
        from app.core.client_ip import client_ip  # noqa: PLC0415 - avoids a settings cycle

        await enforce_limit(
            redis,
            key=key_builder(client_ip(request)),
            limit=limit,
            window_seconds=window_seconds,
            action=action,
        )

    return _check


async def enforce_limit(
    redis: Redis,
    *,
    key: str,
    limit: int,
    window_seconds: int,
    action: str,
) -> None:
    """
    The check itself, callable directly rather than only as a dependency.

    A route dependency runs BEFORE the handler, which is wrong whenever the expensive thing
    it protects happens only on some paths through that handler. Report generation is the
    case that forced this out: its endpoint is idempotent and doubles as the client's READ
    path, so as a dependency the limiter charged a candidate for re-opening a report that was
    already finished — and locked them out of generating a new one.

    Callers that need it on every request keep using `rate_limiter()`; callers that need it
    at one specific point call this.

    Fails OPEN on a Redis error, same as the dependency: a limiter outage must not take down
    the interview flow.
    """
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
    except RedisError:
        logger.exception("rate_limit_check_failed", key=key, action=action)
        return

    if count > limit:
        ttl = await _safe_ttl(redis, key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded for {action}: {limit} requests per "
                f"{window_seconds}s. Try again in {ttl}s."
            ),
        )


async def _safe_ttl(redis: Redis, key: str) -> int:
    try:
        ttl = await redis.ttl(key)
        return ttl if ttl and ttl > 0 else 0
    except RedisError:
        return 0
