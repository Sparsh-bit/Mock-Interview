"""
A fleet-wide daily request counter — db/daily_counter.py

WHAT IT IS FOR. Some ceilings are counted in REQUESTS PER DAY rather than in money, and
`AI_DAILY_BUDGET_USD` is structurally blind to every one of them: a free-tier call costs
$0.00, so the spend cap never moves no matter how many are made. Two callers need exactly
this and for exactly that reason —

  ai:rung   the free-tier burst provider (services/ai/burst_rung.py), ~2,000/day
  judge0    the PUBLIC Judge0 CE instance (api/v1/code.py), shared with the whole internet

EXTRACTED RATHER THAN COPIED. This is the burst rung's counter, unchanged in behaviour and
moved here when the second caller arrived. Two independent copies of a Redis accounting
routine is two places for the expiry logic to be got subtly differently wrong.

THREE PROPERTIES WORTH KNOWING, all inherited deliberately:

  THE COUNT IS THE HIGHER OF REDIS AND THIS PROCESS'S OWN TALLY. Neither source failing can
  under-report, and under-reporting is the only direction that costs anything.

  IT RESERVES BEFORE THE CALL, never on success. Incrementing after a success would let a
  burst of concurrent requests all read one-below-the-limit and all proceed. Counting an
  attempt that then fails is the conservative error, and "must not exceed" is the requirement.

  A REDIS OUTAGE DEGRADES TO PER-PROCESS. Each process then caps itself, so the fleet ceiling
  becomes limit x processes. That is a degradation of an already-degraded state; the
  alternative — refusing everything whenever Redis blinks — throws the fallback away at
  exactly the moment it is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

logger = structlog.get_logger(__name__)

#: Per-process tallies, keyed by the same day-key Redis uses. Used when Redis is unreachable.
#: One dict for every counter: the key carries the name, so callers cannot collide.
_tallies: dict[str, int] = {}

#: Long enough that a counter written just before midnight is still readable the next day, and
#: short enough that yesterday's key cannot survive to be double-counted.
_KEY_TTL_SECONDS = 60 * 60 * 36


def _key(name: str) -> str:
    """UTC, because the process timezone is not a thing to depend on across hosts."""
    return f"{name}:requests:{datetime.now(UTC).date().isoformat()}"


async def used_today(name: str) -> int:
    """How many requests have been reserved today, across the fleet where possible."""
    key = _key(name)
    local = _tallies.get(key, 0)

    from app.db.redis import cache_get, get_redis  # noqa: PLC0415

    try:
        raw = await cache_get(get_redis(), key)
        shared = int(raw) if raw else 0
    except Exception:  # noqa: BLE001 — accounting must never break a request
        logger.warning("daily_counter_read_failed_using_local", name=name, local=local)
        return local
    return max(local, shared)


async def reserve(name: str) -> None:
    """Reserve one request against today's allowance. Call BEFORE the request, not after."""
    key = _key(name)
    _tallies[key] = _tallies.get(key, 0) + 1
    # Keep the dict from growing without bound across a long-lived process. Only this
    # counter's stale keys — another name's tally is not ours to discard.
    prefix = f"{name}:requests:"
    for stale in [k for k in _tallies if k.startswith(prefix) and k != key]:
        _tallies.pop(stale, None)

    from app.db.redis import get_redis  # noqa: PLC0415

    try:
        redis = get_redis()
        count = await redis.incr(key)
        # Set the expiry only on the first write of the day, so a mid-day INCR cannot keep
        # pushing the window out and leave yesterday's count alive into tomorrow.
        if count == 1:
            await redis.expire(key, _KEY_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning(
            "daily_counter_write_failed_local_only", name=name, local=_tallies[key]
        )


async def has_budget(name: str, limit: int) -> bool:
    """False once today's allowance is spent. `limit <= 0` disables the cap."""
    if limit <= 0:
        return True
    used = await used_today(name)
    if used < limit:
        return True
    logger.warning("daily_request_limit_reached", name=name, used=used, limit=limit)
    return False
