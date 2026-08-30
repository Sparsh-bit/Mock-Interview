"""
Standing — api/v1/progress.py

What the candidate is chasing, in one response: their rating, where that sits on the
ladder, how far the next rung is, the cleared-round ledger by tier, and where they
stand against everyone else.

The shape is deliberate. A progression screen that shows only a number is a score;
one that shows the number, what it claims about you, and the exact distance to the
next thing is a ladder. The second one is what brings people back.

Everything here is derived from the append-only ledger (models/progress.py). There
is no stored current-rating to go stale.

`GET /progress/me` was added alongside `GET /progress`, not instead of it. This one answers
"where do I stand on the ladder"; that one answers "what should I do next" — the streak, the
milestones, the unfinished session and the difficulty the next round opens at. They are
separate because they are read by different screens and one of them is much cheaper.

────────────────────────────────────────────────────────────────────────────────────────────
THE RE-ENGAGEMENT CHANNEL, DECIDED AND STATED
────────────────────────────────────────────────────────────────────────────────────────────

THE CHANNEL IS THIS ENDPOINT. In-app, pull, rendered on a page the candidate chose to open.
Nothing here is sent to anybody.

That is a decision rather than a limitation, and there were three reasons for it.

1. NO OUTBOUND CHANNEL EXISTS, and the one that looks like it does is not one. Settings has an
   "email notifications" toggle whose entire implementation is a `localStorage` key
   (`interviewos:emailNotifications`); there is no mail sender, no push service and no SMS
   vendor anywhere in this repository. Building the first one is not a feature flag — it is a
   new vendor, a new row in `docs/COMPLIANCE.md`'s §16 cross-border table, a new consent
   purpose in `models/consent.py`, and a deliverability surface. That is its own piece of
   work and it should be decided on its own merits, not slipped in underneath a streak.

2. THE CONSENT THIS WOULD NEED IS NOT THE CONSENT ANYONE HAS GIVEN. `CONSENT_PURPOSES` covers
   terms, the privacy notice, an 18+ declaration, resume processing, cross-border transfer and
   analytics. None of those is agreement to be CONTACTED, and DPDP §6 asks for consent that is
   specific — reading "I have read what happens to my data" as "you may email me when I stop
   practising" is exactly the bundling that section exists to forbid. So an outbound message
   today would go to people who have not agreed to receive one, which the brief rules out and
   which is independently the wrong thing to do.

3. AN IN-APP NUDGE CANNOT MANUFACTURE URGENCY, AND THAT IS THE POINT. A push notification
   arrives whether or not the person wanted to think about placements this evening; a line on
   the dashboard is read by somebody who already opened the dashboard. `docs/COMPLIANCE.md`
   records that this product has no reliable way to know it is not talking to a minor — the
   18+ declaration at signup has a documented window — and DPDP §9 prohibits both behavioural
   monitoring of children and advertising directed at them. A pull surface is the one shape
   where "we got that wrong" costs a candidate a sentence they did not need to read.

WHEN AN OUTBOUND CHANNEL DOES EXIST, the shape this should take is: a new
`PURPOSE_REENGAGEMENT` in `models/consent.py`, unchecked by default at signup, withdrawable
through the existing `/legal/consent` endpoint, and a send path that reads the consent ledger
per recipient rather than a cached flag. The messages worth sending are the two the brief
names — a lapsing streak and newly unlocked practice in a weak area — and both are already
computed here, so the send path would be a reader of this rather than a second opinion about
it. It is deliberately not built now.

────────────────────────────────────────────────────────────────────────────────────────────
WHAT THIS DELIBERATELY DOES NOT RETURN
────────────────────────────────────────────────────────────────────────────────────────────

No countdown to a lapsing streak, no comparison to other candidates, no "you have not
practised in N days", and no reward attached to the streak at all. See `streak.py` and
`milestones.py`, which each state at length why.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys
from app.db.session import get_db
from app.models.progress import RatingEvent
from app.services.progress import milestones as milestone_service
from app.services.progress import progression
from app.services.progress import streak as streak_service
from app.services.progress.rating import (
    BASE_RATING,
    RANKS,
    TIERS,
    Tier,
    next_rank,
    rank_for,
)
from app.services.progress.recorder import current_rating

router = APIRouter(prefix="/progress", tags=["progress"])

#: These are cheap indexed reads, so this is not about cost. It is about one
#: authenticated client in a retry loop — or a scraper holding a valid token — issuing
#: unbounded queries against a database shared with everyone else. The percentile query
#: in particular is a window function over every active user's newest rating.
_read_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_READ_PER_MINUTE,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_read(user_id),
    action="loading your standing",
)


class TierProgress(BaseModel):
    tier: str
    label: str
    #: The score out of 100 this tier counts as cleared at.
    clear_bar: int
    #: Rounds cleared at this tier. Monotonic — this is the showable credential.
    cleared: int
    #: Rounds attempted at this tier, so "3 of 11" reads honestly rather than
    #: implying every round cleared.
    attempted: int


class RankInfo(BaseModel):
    name: str
    meaning: str
    floor: int


class RoundSummary(BaseModel):
    kind: str
    tier: str
    score: float
    cleared: bool
    delta: int
    rating_after: int
    at: datetime
    #: Why the delta was what it was, in one line the candidate can act on.
    note: str


class ProgressResponse(BaseModel):
    rating: int
    peak_rating: int
    rank: RankInfo
    next_rank: RankInfo | None
    #: Points to the next rung, or 0 at the top. Given explicitly rather than left
    #: as arithmetic on the client, because this is the number people fixate on.
    points_to_next: int
    #: 0-100. How many rated candidates this one is at or above.
    percentile: int | None
    rated_rounds: int
    total_cleared: int
    tiers: list[TierProgress]
    recent: list[RoundSummary]
    #: The whole ladder, so the UI can show what is still ahead rather than only the
    #: next step. Seeing "Placement Elite" from Shortlisted is the point.
    ladder: list[RankInfo]


def _note(ev: RatingEvent) -> str:
    """
    One line explaining this round's delta.

    Without it, a two-point gain on a round the candidate thought went well reads as
    the app being broken. It is not broken — they were expected to do that well — and
    saying so is what turns the rating from an opaque score into something they can
    aim at.
    """
    detail = ev.detail or {}
    expected = float(detail.get("expected") or 0)
    scale = float(detail.get("applied_scale") or 1)
    overlap = float(detail.get("topic_overlap") or 0)
    today = int(detail.get("rounds_today") or 0)

    if ev.delta <= 0:
        if expected > 0.7:
            return "You were expected to clear this comfortably, so falling short cost you."
        return "Below the bar for this tier. The rating moves on how you do against expectation."
    if scale < 0.6 and overlap >= 0.5:
        return "Mostly topics you have already been rated on — revision counts for less."
    if scale < 0.6 and today > 2:
        return "Several rounds today already. Gains taper so the number cannot be crammed."
    if expected > 0.85:
        return "You have already proved this tier. A harder round is the only way up now."
    if ev.delta >= 20:
        return "You beat expectation by a wide margin on a hard round."
    return "Solid round against a fair expectation."


class StreakOut(BaseModel):
    days: int
    practised_today: bool
    best: int
    #: The zone the days were counted in, so a candidate who thinks the number is wrong can be
    #: shown what it was computed against.
    timezone: str
    #: A live streak that today has not yet extended. STATED, never counted down.
    at_risk: bool


class MilestoneOut(BaseModel):
    key: str
    name: str
    claim: str
    #: What it takes, readable BEFORE it is earned — the property that makes this a goal
    #: rather than a surprise reward.
    requirement: str
    earned: bool
    #: 0.0–1.0. Honest partial credit rather than a binary that reads as nothing happening.
    fraction: float


class ResumeOut(BaseModel):
    session_id: uuid.UUID
    questions_answered: int
    hours_ago: int


class ProgressOut(BaseModel):
    streak: StreakOut
    rating: int
    rank: str
    next_rank: str | None
    #: How far through the current rank, 0.0–1.0.
    rank_fraction: float
    #: Everything earned, then the two nearest not yet earned.
    milestones: list[MilestoneOut]
    #: An interview started and left, if there is one worth coming back to.
    resume: ResumeOut | None
    #: What the next round will OPEN at — easy | medium | hard — given what they have proven.
    #: Shown so the progression is visible rather than merely happening.
    opens_at: str


@router.get(
    "",
    summary="The candidate's rating, rank and cleared-round ledger",
    dependencies=[Depends(_read_rate_limit)],
)
async def get_progress(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ProgressResponse:
    user_id: uuid.UUID = current_user.user_id

    rating = await current_rating(db, user_id)

    # Peak is read from the ledger rather than tracked, so it cannot drift. It is
    # shown because a rating that has dipped is discouraging without the reminder
    # that the candidate has already been higher — and the peak is honest, unlike
    # simply hiding the dip.
    peak = int(
        await db.scalar(
            select(func.max(RatingEvent.rating_after)).where(RatingEvent.user_id == user_id)
        )
        or rating
    )

    # Per-tier attempted/cleared in one pass rather than a query per tier.
    tier_rows = (
        await db.execute(
            select(
                RatingEvent.tier,
                func.count().label("attempted"),
                func.sum(case((RatingEvent.cleared.is_(True), 1), else_=0)).label("cleared"),
            )
            .where(RatingEvent.user_id == user_id)
            .group_by(RatingEvent.tier)
        )
    ).all()
    by_tier = {r.tier: (int(r.attempted or 0), int(r.cleared or 0)) for r in tier_rows}

    tiers = [
        TierProgress(
            tier=t.value,
            label=TIERS[t].label,
            clear_bar=TIERS[t].clear_bar,
            attempted=by_tier.get(t.value, (0, 0))[0],
            cleared=by_tier.get(t.value, (0, 0))[1],
        )
        # Explicit order, hardest last, so the ladder reads the same way everywhere.
        for t in (Tier.FOUNDATION, Tier.CORE, Tier.PANEL)
    ]

    rated_rounds = sum(t.attempted for t in tiers)
    total_cleared = sum(t.cleared for t in tiers)

    # Percentile against every other rated candidate's CURRENT rating. A window
    # function picks each user's newest event, then we count how many sit at or below
    # this candidate. Restricted to the last 180 days so the comparison is against
    # people actually using the product, not a graveyard of abandoned accounts that
    # would inflate everyone's standing.
    percentile: int | None = None
    if rated_rounds > 0:
        since = datetime.now(UTC) - timedelta(days=180)
        ranked = (
            select(
                RatingEvent.user_id,
                RatingEvent.rating_after,
                func.row_number()
                .over(
                    partition_by=RatingEvent.user_id,
                    order_by=(RatingEvent.created_at.desc(), RatingEvent.id.desc()),
                )
                .label("rn"),
            )
            .where(RatingEvent.created_at >= since)
            .subquery()
        )
        latest = select(ranked.c.user_id, ranked.c.rating_after).where(ranked.c.rn == 1).subquery()
        row = (
            await db.execute(
                select(
                    func.count().label("total"),
                    func.sum(
                        case((latest.c.rating_after <= rating, 1), else_=0).cast(Integer)
                    ).label("at_or_below"),
                ).select_from(latest)
            )
        ).one()
        total = int(row.total or 0)
        # Below this there is no cohort to be a percentile of, and "top 50%" out of
        # three users is a lie that undermines every other number on the screen.
        if total >= 20:
            percentile = int(round((int(row.at_or_below or 0) / total) * 100))

    recent_rows = (
        await db.execute(
            select(RatingEvent)
            .where(RatingEvent.user_id == user_id)
            .order_by(RatingEvent.created_at.desc(), RatingEvent.id.desc())
            .limit(10)
        )
    ).scalars()

    nxt = next_rank(rating)
    return ProgressResponse(
        rating=rating,
        peak_rating=max(peak, rating),
        rank=RankInfo(**rank_for(rating).__dict__),
        next_rank=RankInfo(**nxt.__dict__) if nxt else None,
        points_to_next=max(0, nxt.floor - rating) if nxt else 0,
        percentile=percentile,
        rated_rounds=rated_rounds,
        total_cleared=total_cleared,
        tiers=tiers,
        recent=[
            RoundSummary(
                kind=ev.kind,
                tier=ev.tier,
                score=round(float(ev.score), 1),
                cleared=bool(ev.cleared),
                delta=int(ev.delta),
                rating_after=int(ev.rating_after),
                at=ev.created_at,
                note=_note(ev),
            )
            for ev in recent_rows
        ],
        ladder=[RankInfo(**r.__dict__) for r in RANKS],
    )


@router.get("/base", summary="Where a new candidate starts, for onboarding copy")
async def get_base() -> dict:
    """Static, so the UI can explain the ladder before a candidate has any history."""
    return {
        "base_rating": BASE_RATING,
        "ladder": [r.__dict__ for r in RANKS],
        "tiers": [
            {"tier": t.value, "label": TIERS[t].label, "clear_bar": TIERS[t].clear_bar}
            for t in (Tier.FOUNDATION, Tier.CORE, Tier.PANEL)
        ],
    }


@router.get("/me", response_model=ProgressOut, dependencies=[Depends(_read_rate_limit)])
async def my_progress(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ProgressOut:
    """Everything the dashboard needs to say what this candidate has built."""
    user_id = current_user.user_id

    streak = await streak_service.for_user(db, user_id)
    progress = await milestone_service.progress_for(db, user_id)
    rank, ahead, fraction = milestone_service.rank_progress(progress.rating)
    resume = await progression.resume_point(db, user_id)

    earned = {m.key for m in milestone_service.earned(progress)}
    upcoming = milestone_service.upcoming(progress)
    rows = [
        MilestoneOut(
            key=m.key,
            name=m.name,
            claim=m.claim,
            requirement=m.requirement,
            earned=True,
            fraction=1.0,
        )
        for m in milestone_service.MILESTONES
        if m.key in earned
    ] + [
        MilestoneOut(
            key=m.key,
            name=m.name,
            claim=m.claim,
            requirement=m.requirement,
            earned=False,
            fraction=round(f, 3),
        )
        for m, f in upcoming
    ]

    return ProgressOut(
        streak=StreakOut(
            days=streak.days,
            practised_today=streak.practised_today,
            best=streak.best,
            timezone=streak.timezone,
            at_risk=streak.at_risk,
        ),
        rating=progress.rating,
        rank=rank,
        next_rank=ahead,
        rank_fraction=round(fraction, 3),
        milestones=rows,
        resume=(
            ResumeOut(
                session_id=resume.session_id,
                questions_answered=resume.questions_answered,
                hours_ago=resume.hours_ago,
            )
            if resume
            else None
        ),
        # Reported with `self_rating=None`: this is what the ledger alone says, before the
        # candidate has been asked how they feel today. Showing it as a promise the panel then
        # ignores would be worse than not showing it, so the panel's own floor uses the same
        # function with the claim included.
        opens_at=progression.opening_difficulty(
            rating=progress.rating, cleared=progress.cleared, self_rating=None
        ),
    )
