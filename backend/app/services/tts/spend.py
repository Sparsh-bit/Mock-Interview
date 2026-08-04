"""
TTS spend, per UTC day — services/tts/spend.py

Its own counter, separate from the AI budget. TTS is priced per CHARACTER and AI per token,
and at ElevenLabs Creator rates a GD round of neural speech costs about twelve times every AI
call in that round combined — so sharing one budget would mean speech quietly consuming the
allowance that scores interviews.

Same shape as the AI counter in anthropic_provider, deliberately: Redis is the shared source
of truth, with an in-process tally that a Redis outage falls back to. A money guard must not
fail OPEN — a Redis-only implementation reads 0.0 forever and the cap silently stops existing.
Worst case the ceiling becomes per-instance rather than global, which is a degradation rather
than an absence.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

logger = structlog.get_logger(__name__)

_local: dict[str, float] = {}


def _key() -> str:
    return f"tts:spend:{datetime.now(UTC):%Y-%m-%d}"


async def tts_spend_today() -> float:
    """The higher of the shared and local tallies, so neither failing under-reports."""
    key = _key()
    local = _local.get(key, 0.0)
    try:
        from app.db.redis import cache_get, get_redis  # noqa: PLC0415

        raw = await cache_get(get_redis(), key)
        return max(float(raw) if raw else 0.0, local)
    except Exception:  # noqa: BLE001 — accounting must never break a request
        logger.warning("tts_spend_read_failed_using_local", local_usd=round(local, 4))
        return local


async def record_tts_spend(amount: float) -> None:
    """Local first, so the spend is counted even if Redis is unreachable."""
    if amount <= 0:
        return
    key = _key()
    _local[key] = _local.get(key, 0.0) + amount
    for stale in [k for k in _local if k != key]:
        del _local[stale]

    try:
        from app.db.redis import get_redis  # noqa: PLC0415

        redis = get_redis()
        await redis.incrbyfloat(key, amount)
        await redis.expire(key, 60 * 60 * 48)
    except Exception:  # noqa: BLE001
        logger.warning("tts_spend_record_failed_counted_locally", amount=amount)
