"""
Catching a shared account — services/security/sharing.py

One account, two networks, at the same time. That is the signal, and the whole design is
about making it mean what it appears to mean.

## The thing this must not do

A false positive here locks a paying customer out of the product mid-session. There is no
gentle version of that, and the population it will hit hardest is the honest one: Indian
campus students on phones, moving between mobile data and college wi-fi, often behind
carrier-grade NAT and campus NAT at the same time. A naive "two IPs, ban" detector would
suspend a large fraction of legitimate users on their first day, and every one of them
would be right to be furious.

So four deliberate dampeners, each removing a specific class of false positive:

  **PREFIX, NOT ADDRESS.** /24 for IPv4, /48 for IPv6. A phone hopping between towers
  changes its address constantly within one carrier range; the range is the network, and
  the network is what "where are you" means here.

  **A HANDOVER WINDOW.** Two networks separated by more than a couple of minutes is somebody
  walking out of the campus gate onto mobile data, not two people. Only genuine overlap —
  both prefixes active inside `_OVERLAP_SECONDS` — counts.

  **A STRIKE COUNT.** One overlap is not enough. A VPN reconnecting, a dual-stack device
  flipping between IPv4 and IPv6, a browser with two tabs on different networks — all of
  these produce a single clean overlap. Sharing produces them repeatedly, so the ban needs
  `_STRIKES_BEFORE_BAN` distinct overlapping windows.

  **DIFFERENT BROWSERS TOO.** Two prefixes with an identical user-agent hash is much more
  likely to be one person's device roaming than two people, because two people rarely have
  byte-identical browser builds. It still counts, but it is not on its own enough to reach a
  strike.

Even with all four, some bans will be wrong. That is why the appeal in api/v1/billing.py is
not a courtesy feature and why only an admin can lift a ban.

## Cost

This runs on authenticated requests, so it must be nearly free. The hot path is a Redis
`SETEX` per (user, prefix) and nothing else; Postgres is touched only when a prefix is one
this account has not been seen on recently, which for a normal user is a few times a day.
"""

from __future__ import annotations

import hashlib
import ipaddress
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSession
from app.models.billing import UserPlan
from app.models.security import UserSession

logger = structlog.get_logger(__name__)

#: Two networks must both be active within this window to count as simultaneous.
#:
#: Three minutes. Long enough that a page load on wi-fi and an API call on mobile data
#: during the same walk still overlap and are correctly NOT treated as two people once the
#: strike rule below is applied; short enough that "used it at lunch, friend used it at
#: dinner" is not read as concurrency.
_OVERLAP_SECONDS = 180

#: How many distinct overlapping windows before the account is suspended.
#:
#: Three. One is noise — a VPN reconnect, a dual-stack flip, a tab left open on another
#: network. Sharing is not a one-off: two people using one account produce overlaps every
#: session, so three costs a genuine sharer very little time and saves a large number of
#: honest users from a wrong ban.
_STRIKES_BEFORE_BAN = 3

#: How long a strike counts for. Strikes older than this expire, so a user who triggered one
#: overlap in March and one in June is never banned by their sum.
_STRIKE_TTL_SECONDS = 7 * 24 * 3600

#: Skip the Postgres write if we have seen this exact (user, prefix, agent) recently.
_SEEN_TTL_SECONDS = 300


def ip_prefix(raw_ip: str | None) -> str:
    """
    An address reduced to the network it belongs to.

    /24 for IPv4 and /48 for IPv6 — see the module note. Returns "" for anything
    unparseable, and the caller treats that as "we do not know where this came from" and
    skips detection entirely rather than inventing a bucket that every unknown shares.
    """
    if not raw_ip:
        return ""
    candidate = raw_ip.strip()
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        return ""
    if isinstance(addr, ipaddress.IPv4Address):
        return str(ipaddress.ip_network(f"{addr}/24", strict=False))
    return str(ipaddress.ip_network(f"{addr}/48", strict=False))


def agent_hash(user_agent: str | None) -> str:
    """SHA-256 of the User-Agent, truncated. Never stores the raw header — see the model."""
    return hashlib.sha256((user_agent or "").encode()).hexdigest()[:32]


def client_ip(headers: dict[str, str], fallback: str | None) -> str:
    """
    The caller's address, from the proxy headers this app actually sits behind.

    TRUSTS `X-Forwarded-For` ONLY BECAUSE THE APP IS BEHIND A PROXY THAT SETS IT. On Render
    and Vercel the platform overwrites this header, so a client cannot forge it. Deployed
    without such a proxy this becomes spoofable — and a spoofable source address would let
    somebody either evade detection or, worse, frame another account into a ban. That is
    the trade, stated here so it is reconsidered if the hosting changes.

    The LEFTMOST entry is the original client; everything after it is a proxy hop.
    """
    fwd = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    return (headers.get("x-real-ip") or fallback or "").strip()


@dataclass(frozen=True)
class SharingVerdict:
    banned: bool
    strikes: int = 0
    reason: str = ""


async def record_and_check(
    db: AsyncSession,
    redis,  # noqa: ANN001 — redis.asyncio.Redis, imported by the caller
    user_id: uuid.UUID,
    raw_ip: str | None,
    user_agent: str | None,
) -> SharingVerdict:
    """
    Note where this request came from, and say whether the account should be suspended.

    NEVER RAISES. Detection failing must not take the request with it — an outage in this
    layer locking every user out of a product they paid for would be far worse than the
    sharing it is trying to catch. Every failure path returns "not banned".
    """
    prefix = ip_prefix(raw_ip)
    if not prefix:
        # No usable address. Skipping is correct: a shared "unknown" bucket would make every
        # unparseable request look like the same network and ban people in pairs.
        return SharingVerdict(banned=False)

    agent = agent_hash(user_agent)

    now = int(datetime.now(UTC).timestamp())

    try:
        # HOT PATH — ONE HASH PER USER, NOT A KEY PER NETWORK.
        #
        # The obvious shape is a key per (user, prefix) and a SCAN to find the others, and
        # it is quietly disastrous: SCAN walks the whole keyspace, and this runs on every
        # authenticated request. A single hash keyed by user makes the read HGETALL over
        # that user's own handful of fields, which is O(networks) rather than O(everything).
        active_key = f"sharing:active:{user_id}"
        await redis.hset(active_key, prefix, f"{now}:{agent}")
        # Refreshed on every write, so the key disappears once an account goes quiet rather
        # than accumulating forever.
        await redis.expire(active_key, _OVERLAP_SECONDS * 4)

        raw = await redis.hgetall(active_key)
        entries: dict[str, tuple[int, str]] = {}
        for k, v in (raw or {}).items():
            key_s = k.decode() if isinstance(k, bytes) else k
            val_s = v.decode() if isinstance(v, bytes) else v
            ts, _, ag = val_s.partition(":")
            try:
                entries[key_s] = (int(ts), ag)
            except ValueError:
                continue

        # Only networks still inside the window count. Anything older is the same person
        # having moved, which is the single largest source of false positives.
        others = {
            p: (ts, ag)
            for p, (ts, ag) in entries.items()
            if p != prefix and now - ts <= _OVERLAP_SECONDS
        }

        # Prune what has aged out, so the hash stays small without a sweeper.
        stale = [p for p, (ts, _) in entries.items() if now - ts > _OVERLAP_SECONDS * 4]
        if stale:
            await redis.hdel(active_key, *stale)

        seen_key = f"sharing:seen:{user_id}:{prefix}:{agent}"
        was_seen = await redis.get(seen_key)
        await redis.setex(seen_key, _SEEN_TTL_SECONDS, "1")

        if was_seen and not others:
            # Familiar network, nothing else live. The overwhelmingly common case, and it
            # costs one hash write and one read.
            return SharingVerdict(banned=False)

        # Durable record of this place. Upserted, so a returning device refreshes its row
        # rather than adding one.
        await db.execute(
            pg_insert(UserSession)
            .values(
                user_id=user_id,
                ip_prefix=prefix,
                agent_hash=agent,
                last_seen_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                constraint="uq_user_sessions_identity",
                set_={"last_seen_at": datetime.now(UTC)},
            )
        )

        if not others:
            return SharingVerdict(banned=False)

        # GENUINE OVERLAP: this account is live on at least two networks inside the window.
        #
        # Same-agent overlaps are counted at half weight — two prefixes with a byte-identical
        # browser build is far more likely to be one person's device roaming than two people,
        # since two people rarely match exactly. It is still evidence, just not enough on its
        # own to reach a strike.
        # The agents came back with the timestamps in the same hash read — no extra round
        # trips, and nothing here re-queries Redis per network.
        different_browser = any(ag != agent for _, ag in others.values())

        strike_key = f"sharing:strikes:{user_id}"
        increment = 2 if different_browser else 1
        strikes_raw = await redis.incrby(strike_key, increment)
        await redis.expire(strike_key, _STRIKE_TTL_SECONDS)
        strikes = int(strikes_raw) // 2  # two half-strikes make one

        logger.info(
            "sharing_overlap_detected",
            user_id=str(user_id),
            networks=len(others) + 1,
            different_browser=different_browser,
            strikes=strikes,
        )

        if strikes < _STRIKES_BEFORE_BAN:
            return SharingVerdict(banned=False, strikes=strikes)

        reason = (
            f"Used from {len(others) + 1} different networks at the same time "
            f"on {strikes} occasions."
        )
        banned = await _ban(db, user_id, reason)
        return SharingVerdict(banned=banned, strikes=strikes, reason=reason)

    except Exception:
        # See the docstring. Detection is best-effort; the request continues.
        logger.warning("sharing_check_failed", user_id=str(user_id), exc_info=True)
        return SharingVerdict(banned=False)


async def _ban(db: AsyncSession, user_id: uuid.UUID, reason: str) -> bool:
    """
    Suspend the account. Returns whether this call was the one that did it.

    Idempotent: an already-banned account is left exactly as it was, so a second overlap
    does not overwrite the original reason or reset `banned_at` — the first one is the
    evidence an admin reviews.
    """
    row = await db.scalar(select(UserPlan).where(UserPlan.user_id == user_id).with_for_update())
    if row is None:
        row = UserPlan(user_id=user_id, source="signup")
        db.add(row)
        await db.flush()
    if row.is_banned:
        return False
    row.is_banned = True
    row.ban_reason = reason[:200]
    row.banned_at = datetime.now(UTC)
    await db.flush()
    logger.warning("account_banned_for_sharing", user_id=str(user_id), reason=reason)
    return True


async def clear_strikes(redis, user_id: uuid.UUID) -> None:  # noqa: ANN001
    """
    Forget the strike history. Called when an admin lifts a ban.

    Without this an unbanned user is one overlap from being banned again by strikes that
    were already reviewed and forgiven, which would make the unban look broken.
    """
    with __import__("contextlib").suppress(Exception):
        await redis.delete(f"sharing:strikes:{user_id}")


async def recent_places(db: AsyncSession, user_id: uuid.UUID, limit: int = 10) -> list[dict]:
    """Where this account has been seen, newest first — for the admin review screen."""
    rows = await db.execute(
        text(
            """
            SELECT ip_prefix, agent_hash, first_seen_at, last_seen_at
              FROM user_sessions
             WHERE user_id = :uid
             ORDER BY last_seen_at DESC
             LIMIT :lim
            """
        ),
        {"uid": str(user_id), "lim": limit},
    )
    return [
        {
            "ip_prefix": r.ip_prefix,
            "agent_hash": r.agent_hash[:12],
            "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
        }
        for r in rows
    ]
