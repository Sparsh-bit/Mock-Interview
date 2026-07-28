"""
Redis Client — db/redis.py

Async Redis connection using redis-py with asyncio support.
Compatible with Upstash Redis (serverless, TLS required for cloud URLs).

All cache operations in this application go through get_redis() dependency.
Never create Redis connections manually in services.
"""

from __future__ import annotations

import structlog
from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import RedisError

from app.core.config import settings

logger = structlog.get_logger(__name__)

# ─── Connection pool ──────────────────────────────────────────────────────────

_pool: ConnectionPool | None = None


def _create_pool() -> ConnectionPool:
    """Create the Redis connection pool from settings."""
    redis_url = settings.REDIS_URL

    # The rediss:// scheme automatically enables TLS; don't pass ssl manually
    # (ConnectionPool.from_url handles it). Upstash requires TLS, so ensure URL
    # uses rediss://, not redis://.
    return ConnectionPool.from_url(
        redis_url,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=True,
        retry=Retry(ExponentialBackoff(cap=2, base=0.1), retries=3),
        retry_on_error=[ConnectionRefusedError, TimeoutError],
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )


def get_redis_pool() -> ConnectionPool:
    """Returns the singleton connection pool, creating it if needed."""
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = _create_pool()
    return _pool


async def close_redis_pool() -> None:
    """Close the connection pool. Call during application shutdown."""
    global _pool  # noqa: PLW0603
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("redis_pool_closed")


# ─── FastAPI dependency ───────────────────────────────────────────────────────


def get_redis() -> Redis:
    """
    FastAPI dependency — returns an async Redis client.
    Shares the application connection pool.

    Usage:
        @router.get("/session/{id}")
        async def get_session(
            session_id: str,
            redis: Redis = Depends(get_redis),
        ):
            cached = await redis.get(f"session:{session_id}")
    """
    return Redis(connection_pool=get_redis_pool())


# ─── Cache helpers ────────────────────────────────────────────────────────────

_DEFAULT_TTL: int | None = None


def get_default_ttl() -> int:
    """Lazily resolve the default TTL from settings to avoid import-time evaluation issues."""
    global _DEFAULT_TTL  # noqa: PLW0603
    if _DEFAULT_TTL is None:
        _DEFAULT_TTL = settings.REDIS_DEFAULT_TTL_SECONDS
    return _DEFAULT_TTL


async def cache_set(redis: Redis, key: str, value: str, ttl: int | None = None) -> None:
    """Set a string value with TTL. Silently logs on failure."""
    try:
        await redis.setex(key, ttl if ttl is not None else get_default_ttl(), value)
    except RedisError:
        logger.exception("cache_set_failed", key=key)


async def cache_get(redis: Redis, key: str) -> str | None:
    """
    Get a string value. Returns None on miss or error.

    Decodes explicitly rather than trusting the pool's decode_responses flag: if
    that is ever turned off, every caller would start receiving bytes, and the
    failures would be silent (float(b"1.5") works, but string comparisons and
    JSON parsing do not behave the same way).
    """
    try:
        raw = await redis.get(key)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)
    except RedisError:
        logger.exception("cache_get_failed", key=key)
        return None


async def cache_delete(redis: Redis, key: str) -> None:
    """Delete a key. Silently ignores errors."""
    try:
        await redis.delete(key)
    except RedisError:
        logger.exception("cache_delete_failed", key=key)


# ─── Cache key builders ───────────────────────────────────────────────────────
#
# All cache keys are defined here — never hardcode key strings in services.


class CacheKeys:
    """Namespaced cache key builders for all application entities."""

    @staticmethod
    def interview_session(session_id: str) -> str:
        return f"interview:session:{session_id}"

    @staticmethod
    def question(question_id: str) -> str:
        return f"question:{question_id}"

    @staticmethod
    def user_profile(user_id: str) -> str:
        return f"user:profile:{user_id}"

    @staticmethod
    def rate_limit_interview(user_id: str, window: str = "hourly") -> str:
        return f"rate_limit:interview:{user_id}:{window}"

    @staticmethod
    def rate_limit_ai(user_id: str, window: str = "minute") -> str:
        return f"rate_limit:ai:{user_id}:{window}"

    @staticmethod
    def track_questions(track_id: str) -> str:
        return f"track:questions:{track_id}"

    @staticmethod
    def report(report_id: str) -> str:
        return f"report:{report_id}"


# ─── Health check ─────────────────────────────────────────────────────────────


async def check_redis_connection() -> bool:
    """
    Verify the Redis server is reachable.
    Used by GET /api/v1/health. Never raises — returns False on failure.
    """
    try:
        redis = get_redis()
        await redis.ping()
        return True
    except Exception:
        logger.exception("redis_health_check_failed")
        return False
