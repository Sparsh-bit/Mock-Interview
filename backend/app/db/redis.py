"""
Redis Client — db/redis.py

Async Redis connection using redis-py with asyncio support.
Compatible with Upstash Redis (serverless, TLS required for cloud URLs).

All cache operations in this application go through get_redis() dependency.
Never create Redis connections manually in services.
"""

from __future__ import annotations

import base64

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


#: Largest single value cache_set_bytes will store. One utterance of MP3 is tens of
#: kilobytes; anything near a megabyte is a vendor returning something unexpected, and Redis
#: memory is shared with rate limits and spend counters that matter more.
_MAX_CACHED_BYTES = 512 * 1024


async def cache_set(redis: Redis, key: str, value: str, ttl: int | None = None) -> None:
    """Set a string value with TTL. Silently logs on failure."""
    try:
        await redis.setex(key, ttl if ttl is not None else get_default_ttl(), value)
    except RedisError:
        logger.exception("cache_set_failed", key=key)


async def cache_set_bytes(key: str, value: bytes, ttl_seconds: int) -> None:
    """
    Cache binary data — audio — through the shared pool.

    BASE64, not raw bytes, and that is forced by the pool rather than chosen: the connection
    is built with decode_responses=True, so anything read back is UTF-8 decoded and MP3 bytes
    are not valid UTF-8. The alternatives were a second connection pool with decoding off, or
    this. A ~33% size penalty on a TTL-bounded ~30KB utterance is a better trade than a second
    pool to keep alive and configure.

    Bounded by size as well as TTL. A vendor returning something unexpectedly large should not
    be able to push everything else out of Redis; past the ceiling the cache simply declines
    and the next request re-synthesises.
    """
    if len(value) > _MAX_CACHED_BYTES:
        logger.warning("cache_set_bytes_too_large", key=key, size=len(value))
        return
    try:
        redis = get_redis()
        await redis.setex(key, ttl_seconds, base64.b64encode(value).decode("ascii"))
    except RedisError:
        logger.exception("cache_set_bytes_failed", key=key)


async def cache_get_bytes(key: str) -> bytes | None:
    """Read binary data cached by cache_set_bytes. None on miss, error, or corrupt value."""
    try:
        redis = get_redis()
        raw = await redis.get(key)
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
        return base64.b64decode(text)
    except (RedisError, ValueError, TypeError):
        # ValueError covers a value that is not valid base64 — a truncated write, or a key
        # collision with something else. Treated as a miss so a corrupt entry costs one
        # re-synthesis instead of a 500.
        logger.warning("cache_get_bytes_failed", key=key, exc_info=True)
        return None


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

    @staticmethod
    def rate_limit_report(user_id: str) -> str:
        """
        Report generation. Its own namespace, not the shared AI budget.

        This is the single most expensive call in the app — the largest response, and
        it holds a worker for tens of seconds. It has to be limited independently of
        the per-minute AI budget, because a user who has spent that budget on cheap
        calls must still be able to get their report, and a user hammering report
        generation must not be able to do it by leaving the cheap calls alone.
        """
        return f"rate_limit:report:{user_id}"

    @staticmethod
    def rate_limit_tts(user_id: str) -> str:
        """Speech synthesis. Own namespace — it is metered per character, not per token."""
        return f"rate_limit:tts:{user_id}"

    @staticmethod
    def tts_audio(digest: str) -> str:
        """Cached audio, keyed by a hash of provider + voice + exact text."""
        return f"tts:audio:{digest}"

    @staticmethod
    def rate_limit_read(user_id: str) -> str:
        """
        Plain authenticated reads — standing, profile, stats.

        These cost no AI and touch few rows, so the limit is not about cost. It is about
        one authenticated client in a retry loop, or a scraper with a valid token, being
        able to issue unbounded queries against a shared Postgres. Generous enough that
        no honest UI notices, low enough that a runaway loop stops.
        """
        return f"rate_limit:read:{user_id}"

    @staticmethod
    def rate_limit_admin(user_id: str) -> str:
        """Admin mutations. Own namespace so it cannot borrow another budget."""
        return f"rate_limit:admin:{user_id}"


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
