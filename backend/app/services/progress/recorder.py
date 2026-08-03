"""
Writing a rated round into the ledger — services/progress/recorder.py

The only writer. Called once when a round produces a score: after a report is
generated for an interview, and after a GD round is evaluated.

Everything with a decision in it lives in rating.py and is pure. This module is the
database half: read the current state, ask rating.py what happens, insert one row.
It is deliberately thin, because the interesting properties of the credential are
the ones that have to be testable without a database.

FAILING HERE MUST NEVER FAIL THE ROUND. A candidate who has just finished a
forty-minute interview is not going to accept "your report could not be saved
because the rating ledger was busy". Every entry point swallows and logs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.progress import RatingEvent
from app.services.progress.rating import (
    BASE_RATING,
    Tier,
    rate_round,
)

logger = structlog.get_logger(__name__)


async def current_rating(db: AsyncSession, user_id: uuid.UUID) -> int:
    """
    The newest event's `rating_after`, or the base rating for a new candidate.

    Derived rather than stored — see models/progress.py for why there is no
    `user_rating` row to disagree with this.
    """
    value = await db.scalar(
        select(RatingEvent.rating_after)
        .where(RatingEvent.user_id == user_id)
        .order_by(RatingEvent.created_at.desc(), RatingEvent.id.desc())
        .limit(1)
    )
    return int(value) if value is not None else BASE_RATING


async def rated_round_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """How many rounds have moved this candidate's rating. Drives the K-factor."""
    return int(
        await db.scalar(
            select(func.count()).select_from(RatingEvent).where(RatingEvent.user_id == user_id)
        )
        or 0
    )


async def rounds_rated_today(db: AsyncSession, user_id: uuid.UUID) -> int:
    """
    Rated rounds in the last 24 hours.

    A rolling window rather than a calendar day, deliberately. A calendar day would
    hand a candidate a fresh allowance at midnight, and the people using this app are
    students preparing the night before a drive — the burst this damps is exactly the
    one that straddles midnight.
    """
    since = datetime.now(UTC) - timedelta(hours=24)
    return int(
        await db.scalar(
            select(func.count())
            .select_from(RatingEvent)
            .where(RatingEvent.user_id == user_id, RatingEvent.created_at >= since)
        )
        or 0
    )


def topic_overlap(new_topics: list[str], previous_topics: set[str]) -> float:
    """
    What share of this round's topics the candidate has already been scored on.

    Answering the same eight questions a fifth time is revision. Revision is good for
    them, and it is not new evidence — so it must not move a number other people are
    meant to trust. Returns 0 when we cannot tell, because damping on missing data
    would penalise a candidate for a gap in our own bookkeeping.
    """
    fresh = {t.strip().lower() for t in new_topics if t and t.strip()}
    if not fresh:
        return 0.0
    seen = {t.strip().lower() for t in previous_topics if t and t.strip()}
    if not seen:
        return 0.0
    return len(fresh & seen) / len(fresh)


async def _topics_already_rated(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    """Every topic this candidate has previously been rated on, from the ledger."""
    rows = await db.execute(
        select(RatingEvent.detail).where(
            RatingEvent.user_id == user_id, RatingEvent.detail.isnot(None)
        )
    )
    seen: set[str] = set()
    for (detail,) in rows:
        for t in (detail or {}).get("topics") or []:
            if isinstance(t, str) and t.strip():
                seen.add(t.strip().lower())
    return seen


async def record_round(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
    kind: str,
    tier: Tier,
    score_out_of_100: float,
    topics: list[str] | None = None,
) -> RatingEvent | None:
    """
    Rate one finished round and append it to the ledger.

    Returns the event, or None if nothing was written — which happens for two normal
    reasons and must not be treated as an error: the session was already rated (the
    unique constraint doing its job when a report is regenerated), or the write
    failed and the round is worth more than the number.

    The caller is responsible for the commit. This flushes so the constraint fires
    here, where it can be handled, rather than at an unrelated commit later.
    """
    topics = topics or []
    try:
        rating = await current_rating(db, user_id)
        rounds = await rated_round_count(db, user_id)
        today = await rounds_rated_today(db, user_id)
        overlap = topic_overlap(topics, await _topics_already_rated(db, user_id))

        outcome = rate_round(
            rating=rating,
            rated_rounds=rounds,
            tier=tier,
            score_out_of_100=score_out_of_100,
            topic_overlap=overlap,
            rounds_today=today,
        )

        event = RatingEvent(
            user_id=user_id,
            session_id=session_id,
            kind=kind,
            tier=tier.value,
            score=float(score_out_of_100),
            cleared=outcome.cleared,
            delta=outcome.delta,
            rating_after=outcome.rating_after,
            detail={
                "rating_before": rating,
                "expected": outcome.expected,
                "actual": outcome.actual,
                "applied_scale": outcome.applied_scale,
                "topic_overlap": round(overlap, 4),
                "rounds_today": today,
                "rated_rounds_before": rounds,
                # Stored so the next round's overlap can be computed from the ledger
                # alone, without joining back through sessions to questions.
                "topics": [t.strip() for t in topics if t and t.strip()][:40],
            },
        )
        db.add(event)
        await db.flush()
        logger.info(
            "rating_round_recorded",
            user_id=str(user_id),
            kind=kind,
            tier=tier.value,
            delta=outcome.delta,
            rating_after=outcome.rating_after,
            cleared=outcome.cleared,
        )
        return event

    except IntegrityError:
        # The unique constraint on session_id. Normal: a regenerated report must not
        # bank the same gain twice.
        await db.rollback()
        logger.info("rating_round_already_recorded", session_id=str(session_id))
        return None
    except Exception:
        # A candidate who has just finished a forty-minute interview will not accept
        # "your report failed because the rating ledger was busy".
        logger.exception("rating_round_failed", user_id=str(user_id), kind=kind)
        return None
