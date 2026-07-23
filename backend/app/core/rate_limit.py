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
from fastapi import Depends, HTTPException, status
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
        key = key_builder(str(current_user.user_id))
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

    return _check


async def _safe_ttl(redis: Redis, key: str) -> int:
    try:
        ttl = await redis.ttl(key)
        return ttl if ttl and ttl > 0 else 0
    except RedisError:
        return 0
