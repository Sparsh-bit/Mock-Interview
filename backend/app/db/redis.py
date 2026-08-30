"""
Redis Client — db/redis.py

Async Redis connection using redis-py with asyncio support.

WRITTEN FOR A REDIS SOMEBODY ELSE OPERATES, not for one on localhost. That changes three
things, and none of them announces itself at the point of failure:

  * the connection is TLS (`rediss://`), and a trust-store problem surfaces as a timeout
    rather than as a certificate error
  * the server can move underneath a live pool. A pooled socket open to the node that was
    just replaced is indistinguishable from a healthy one until a command uses it, which is
    why `health_check_interval` below is load-bearing rather than tuning
  * the connection budget is (pool size x replicas) against a ceiling the provider enforces,
    not against a local machine that has no ceiling. `audit_redis_configuration` does that
    arithmetic at startup because nothing else in the process can see past its own pool

All cache operations in this application go through the get_redis() dependency.
Never create Redis connections manually in services.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from urllib.parse import urlsplit

import structlog
from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialWithJitterBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config import settings

logger = structlog.get_logger(__name__)

# ─── Connection pool ──────────────────────────────────────────────────────────

_pool: ConnectionPool | None = None


def url_is_tls(url: str) -> bool:
    """True when the URL selects redis-py's SSLConnection."""
    return urlsplit(url).scheme == "rediss"


def _tls_kwargs(url: str) -> dict[str, object]:
    """
    TLS options, and ONLY for a rediss:// URL.

    redis-py's plaintext Connection forwards unknown kwargs to AbstractConnection, which
    raises TypeError on them — so handing `ssl_ca_certs` to a redis:// pool does not
    "get ignored", it stops the process from building a pool at all. Production setting
    a CA path must not break a developer running against localhost.

    The two verification options are redis-py 8 defaults; they are stated anyway because
    they are the whole security value of the scheme, and a default that is never written
    down is a default nobody notices changing.
    """
    if not url_is_tls(url):
        return {}
    kwargs: dict[str, object] = {
        "ssl_cert_reqs": "required",
        "ssl_check_hostname": True,
    }
    if settings.REDIS_TLS_CA_CERTS:
        kwargs["ssl_ca_certs"] = settings.REDIS_TLS_CA_CERTS
    return kwargs


def _create_pool() -> ConnectionPool:
    """Create the Redis connection pool from settings."""
    redis_url = settings.REDIS_URL

    return ConnectionPool.from_url(
        redis_url,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=True,
        # JITTERED, and that is the point of choosing this over ExponentialBackoff.
        # Every replica loses the same server at the same instant during a failover, so a
        # deterministic schedule has all of them retrying on the same tick — a herd
        # arriving at a node that has only just come back.
        retry=Retry(
            ExponentialWithJitterBackoff(cap=2.0, base=0.1),
            retries=settings.REDIS_MAX_RETRIES,
            supported_errors=(RedisConnectionError, RedisTimeoutError),
        ),
        # THE REDIS EXCEPTIONS, not the builtins. This list previously held
        # ConnectionRefusedError and TimeoutError from builtins; redis-py raises
        # redis.exceptions.ConnectionError / TimeoutError, neither of which inherits from
        # a builtin, so the list matched nothing it was written to match. It only ever
        # worked because Retry's own defaults already cover these two.
        retry_on_error=[RedisConnectionError, RedisTimeoutError],
        # See REDIS_HEALTH_CHECK_INTERVAL_SECONDS: without this, the first request after
        # every provider failover is served a socket to a node that no longer exists.
        health_check_interval=settings.REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        **_tls_kwargs(redis_url),
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
    def panel_turn(session_id: str, digest: str) -> str:
        """
        A written panel turn, keyed by session plus a hash of the stage and the question.

        SCOPED TO THE SESSION, always. A turn quotes the candidate's own last answer and names
        their projects, so it is exactly the kind of content vector_cache's CACHEABLE_FEATURES
        allowlist exists to keep out of a shared pool. This key can never be reached from
        another session even if two candidates are asked a byte-identical question.
        """
        return f"panel:turn:{session_id}:{digest}"

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

    Bounded by its OWN deadline rather than by the retry budget. Real traffic is allowed to
    spend socket_connect_timeout x retries plus backoff riding out a failover blip — that is
    the whole point of the retry configuration — but a liveness probe that takes twenty
    seconds to answer is read by the platform as a dead instance and the replica is recycled
    while it is in fact healthy. So the probe gives up early and reports degraded.
    """
    try:
        redis = get_redis()
        await asyncio.wait_for(
            redis.ping(), timeout=settings.REDIS_HEALTH_PING_TIMEOUT_SECONDS
        )
        return True
    except Exception:
        logger.warning("redis_health_check_failed", exc_info=True)
        return False


# ─── Startup configuration audit ──────────────────────────────────────────────


@dataclass(frozen=True)
class RedisConfigIssue:
    """One thing about the Redis configuration worth telling an operator at boot."""

    code: str
    message: str
    hint: str


#: Fraction of the provider ceiling at which the budget is called out before it is breached.
#: Breaching it is not a graceful degradation — the provider refuses new connections and the
#: symptom is scattered errors on random requests, so the warning has to arrive early enough
#: to act on.
_CEILING_WARN_RATIO = 0.8

#: Hosts where plaintext Redis is a developer's docker-compose rather than a password
#: crossing the public internet in the clear.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


def audit_redis_configuration(
    *,
    url: str,
    environment: str,
    max_connections: int,
    replicas: int,
    ceiling: int,
) -> list[RedisConfigIssue]:
    """
    Everything about the Redis configuration that a single process cannot see for itself.

    Pure — takes the numbers rather than reading settings — so every threshold can be tested
    at the boundary instead of by contriving an environment.

    Returns issues to LOG, never to raise on. main.py's lifespan already refuses to make
    Redis fatal, for the stated reason that every Redis-backed feature degrades rather than
    breaks; a misconfiguration warning has no business being stricter than an outage.
    """
    issues: list[RedisConfigIssue] = []
    host = (urlsplit(url).hostname or "").lower()
    managed = host not in _LOOPBACK_HOSTS

    if environment == "production" and managed and not url_is_tls(url):
        issues.append(
            RedisConfigIssue(
                code="redis_plaintext_in_production",
                message=(
                    f"REDIS_URL points at {host} over plaintext redis://. The AUTH "
                    "password and every cached value cross the network in the clear."
                ),
                hint="Change the scheme to rediss:// — managed providers serve both ports.",
            )
        )

    if managed and ceiling <= 0:
        issues.append(
            RedisConfigIssue(
                code="redis_connection_ceiling_unknown",
                message=(
                    "REDIS_CONNECTION_CEILING is unset, so the connection budget "
                    f"({max_connections} x {replicas} replicas = {max_connections * replicas}) "
                    "is not being checked against anything."
                ),
                hint=(
                    "Set it to the simultaneous-connection limit on your Redis plan. "
                    "See docs/REDIS-CUTOVER.md §1."
                ),
            )
        )
        return issues

    if not managed:
        return issues

    budget = max_connections * replicas
    if budget > ceiling:
        issues.append(
            RedisConfigIssue(
                code="redis_pool_budget_over_ceiling",
                message=(
                    f"Redis connection budget {max_connections} x {replicas} replicas = "
                    f"{budget}, over the provider ceiling of {ceiling}."
                ),
                hint=(
                    "Lower REDIS_MAX_CONNECTIONS or WEB_REPLICA_COUNT. Past the ceiling "
                    "the provider refuses new connections and the symptom is scattered "
                    "errors on random requests, not a clean slowdown."
                ),
            )
        )
    elif budget >= ceiling * _CEILING_WARN_RATIO:
        issues.append(
            RedisConfigIssue(
                code="redis_pool_budget_near_ceiling",
                message=(
                    f"Redis connection budget {max_connections} x {replicas} replicas = "
                    f"{budget}, within {int((1 - _CEILING_WARN_RATIO) * 100)}% of the "
                    f"provider ceiling of {ceiling}."
                ),
                hint="One more replica breaches it. Lower REDIS_MAX_CONNECTIONS first.",
            )
        )

    return issues


def log_redis_configuration_audit() -> list[RedisConfigIssue]:
    """Run the audit against live settings and log each issue. Called from the lifespan."""
    issues = audit_redis_configuration(
        url=settings.REDIS_URL,
        environment=settings.ENVIRONMENT,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        replicas=settings.WEB_REPLICA_COUNT,
        ceiling=settings.REDIS_CONNECTION_CEILING,
    )
    for issue in issues:
        logger.warning(issue.code, message=issue.message, hint=issue.hint)
    return issues
