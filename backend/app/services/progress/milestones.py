"""
What you have actually got better at — services/progress/milestones.py

MILESTONES ARE UNLOCKED BY DEMONSTRATED SKILL, NEVER BY ATTENDANCE. Every one below is a
condition over the rating ledger — rounds CLEARED at a tier, a rating reached, a breadth of
subjects survived — and none of them can be reached by opening the app, by spending money, or
by sitting rounds badly. That is the whole design, and it is the difference between a
milestone and a participation badge.

────────────────────────────────────────────────────────────────────────────────────────────
THE FOUR THINGS THIS MUST NOT BE, AND WHY EACH ONE IS STRUCTURALLY IMPOSSIBLE HERE
────────────────────────────────────────────────────────────────────────────────────────────

NOT A VARIABLE REWARD. Every milestone's condition is a fixed, stated threshold, and
`upcoming()` tells the candidate the next one and exactly how far away it is BEFORE they earn
it. There is no roll, no chance, no surprise drop, no streak-multiplier. A candidate can
always answer "what do I have to do to get that?" from the screen, which is precisely what a
variable-ratio schedule is designed to prevent them from being able to do.

NOT URGENCY. Nothing here expires, decays or is time-limited. A milestone earned is kept, and
one not yet earned waits indefinitely. There are no windows, no "today only", no countdowns.

NOT GUILT. The copy states a fact about the candidate's practice and never characterises them
for the absence of one. There is no "you've fallen behind", no comparison to other users, no
"don't lose your progress".

NOT PARTICIPATION. `streak` appears NOWHERE in these conditions. Days of attendance are
reported elsewhere and unlock nothing, so no milestone can ever be earned by turning up.

The reason this is written down at this length rather than left as good intentions: DPDP §9
prohibits behavioural monitoring and targeted advertising directed at under-18s, and
`docs/COMPLIANCE.md` records that this product's age gate has a window ("an account created
and then abandoned before this call"). Mechanics that work by compulsion are the ones that
would be a problem if a minor reached them, and the honest response is not to build them for
anybody rather than to build them and hope the gate holds.

────────────────────────────────────────────────────────────────────────────────────────────
WHY THE CONDITIONS ARE COUNTS OF CLEARED ROUNDS RATHER THAN OF ROUNDS
────────────────────────────────────────────────────────────────────────────────────────────

`RatingEvent.cleared` is "did this round meet its tier's bar" — 65 at Foundation, 72 at Core,
78 at Panel. Counting rounds SAT would make every milestone purchasable with credits, which
turns the ladder into a receipt. Counting rounds CLEARED means the only way through is to get
better, and the tier bars rising with difficulty means clearing three Panel rounds is a
genuinely different claim from clearing three Foundation ones.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.services.progress.rating import RANKS, Tier


@dataclass(frozen=True, slots=True)
class Progress:
    """What the ledger says about a candidate, reduced to the facts a milestone can read."""

    rating: int
    #: Cleared rounds, by tier. Not rounds sat — see the module docstring.
    cleared: dict[Tier, int]
    #: Distinct subjects the candidate has been scored on across every rated round.
    topics_covered: int
    #: Rounds where the candidate answered every question rather than declining any. Evidence
    #: of composure, which is a real interview skill and is not measured anywhere else.
    rounds_without_declining: int


@dataclass(frozen=True, slots=True)
class Milestone:
    key: str
    name: str
    #: What earning it actually claims about the candidate. Never "you did 10 things" — the
    #: claim has to be about capability or the milestone is a counter with a medal on it.
    claim: str
    #: The condition, stated for the UI so a candidate can read what is required BEFORE
    #: earning it. A milestone whose requirement is only visible afterwards is a surprise
    #: reward, which is the thing this file exists to not be.
    requirement: str
    met: Callable[[Progress], bool]
    #: How far along, 0.0–1.0, for a progress bar. Honest partial credit rather than a binary
    #: that reads as "nothing is happening" for the eight rounds before it flips.
    fraction: Callable[[Progress], float]


def _ratio(have: int, need: int) -> float:
    return min(1.0, have / need) if need else 1.0


MILESTONES: list[Milestone] = [
    Milestone(
        key="first_cleared",
        name="First round cleared",
        claim="You have held a full round at the bar it was set at.",
        requirement="Clear 1 round at any tier.",
        met=lambda p: sum(p.cleared.values()) >= 1,
        fraction=lambda p: _ratio(sum(p.cleared.values()), 1),
    ),
    Milestone(
        key="core_three",
        name="Core, three times",
        claim="Clearing a Core round once can be a good day. Three times is a level.",
        requirement="Clear 3 Core-tier rounds (72+ each).",
        met=lambda p: p.cleared.get(Tier.CORE, 0) >= 3,
        fraction=lambda p: _ratio(p.cleared.get(Tier.CORE, 0), 3),
    ),
    Milestone(
        key="breadth_eight",
        name="Eight subjects deep",
        claim="You have been scored across eight different subjects, so the score is not one topic you happen to know.",
        requirement="Be scored on 8 distinct subjects.",
        met=lambda p: p.topics_covered >= 8,
        fraction=lambda p: _ratio(p.topics_covered, 8),
    ),
    Milestone(
        key="composure",
        name="Never declined",
        claim="Three rounds where you attempted every question. Saying something beats saying nothing, and panels notice.",
        requirement="Complete 3 rounds without declining a question.",
        met=lambda p: p.rounds_without_declining >= 3,
        fraction=lambda p: _ratio(p.rounds_without_declining, 3),
    ),
    Milestone(
        key="interview_ready",
        name="Interview Ready",
        claim="Your rating says you handle a standard round without falling apart.",
        requirement="Reach a rating of 1400.",
        met=lambda p: p.rating >= 1400,
        fraction=lambda p: _ratio(max(0, p.rating - 1200), 200),
    ),
    Milestone(
        key="panel_cleared",
        name="Panel cleared",
        claim="You have cleared a Panel round — the hardest tier, at a 78 bar.",
        requirement="Clear 1 Panel-tier round (78+).",
        met=lambda p: p.cleared.get(Tier.PANEL, 0) >= 1,
        fraction=lambda p: _ratio(p.cleared.get(Tier.PANEL, 0), 1),
    ),
    Milestone(
        key="offer_ready",
        name="Offer Ready",
        claim="Your rating says you hold up under cross-questioning on your own answers.",
        requirement="Reach a rating of 1600.",
        met=lambda p: p.rating >= 1600,
        fraction=lambda p: _ratio(max(0, p.rating - 1400), 200),
    ),
]


def earned(progress: Progress) -> list[Milestone]:
    """Everything this candidate has actually reached, in the order they are listed."""
    return [m for m in MILESTONES if m.met(progress)]


def upcoming(progress: Progress, limit: int = 2) -> list[tuple[Milestone, float]]:
    """
    The nearest milestones not yet reached, with how far along each one is.

    STATED IN ADVANCE, which is the property that makes this not a variable reward. The
    candidate can see the requirement and the distance before earning it, so the mechanic is a
    goal rather than a surprise. Sorted by how close they are, so the next thing shown is the
    next thing achievable rather than the most impressive one.
    """
    pending = [(m, m.fraction(progress)) for m in MILESTONES if not m.met(progress)]
    pending.sort(key=lambda pair: -pair[1])
    return pending[:limit]


async def progress_for(db, user_id: uuid.UUID) -> Progress:
    """Read the four facts a milestone can be conditioned on out of the rating ledger."""
    from sqlalchemy import func, select  # noqa: PLC0415

    from app.models.progress import RatingEvent  # noqa: PLC0415
    from app.services.progress.recorder import current_rating  # noqa: PLC0415

    rating = await current_rating(db, user_id)

    rows = list(
        await db.execute(
            select(RatingEvent.tier, func.count())
            .where(RatingEvent.user_id == user_id, RatingEvent.cleared.is_(True))
            .group_by(RatingEvent.tier)
        )
    )
    cleared: dict[Tier, int] = {}
    for tier_value, count in rows:
        try:
            cleared[Tier(tier_value)] = int(count)
        except ValueError:
            # A tier this build does not know — an older row, or a renamed tier. Skipped
            # rather than crashed: a milestone screen is not worth a 500, and the count it
            # contributes to is a floor rather than a claim of completeness.
            continue

    # Topics, out of the detail blob the rating writer already stores. Read from there rather
    # than re-derived from questions, because `detail` is what was actually scored — the
    # audit trail — and a second derivation could disagree with the number already shown.
    details = list(
        await db.scalars(
            select(RatingEvent.detail).where(RatingEvent.user_id == user_id)
        )
    )
    topics: set[str] = set()
    without_declining = 0
    for detail in details:
        if not isinstance(detail, dict):
            continue
        for topic in detail.get("topics") or []:
            if isinstance(topic, str) and topic.strip():
                topics.add(topic.strip().lower())
        # `declined` is absent on rows written before it was recorded; absent is not zero, so
        # those rounds simply do not count towards this milestone rather than counting as
        # perfect ones.
        if detail.get("declined") == 0:
            without_declining += 1

    return Progress(
        rating=rating,
        cleared=cleared,
        topics_covered=len(topics),
        rounds_without_declining=without_declining,
    )


def rank_progress(rating: int) -> tuple[str, str | None, float]:
    """
    (current rank name, next rank name, fraction of the way there).

    Reuses `rating.RANKS` rather than restating the ladder, so the milestone screen and the
    report cannot disagree about what "Interview Ready" means.
    """
    from app.services.progress.rating import next_rank, rank_for  # noqa: PLC0415

    here = rank_for(rating)
    ahead = next_rank(rating)
    if ahead is None:
        return here.name, None, 1.0
    span = ahead.floor - here.floor
    return here.name, ahead.name, _ratio(max(0, rating - here.floor), span) if span else 1.0


__all__ = [
    "MILESTONES",
    "RANKS",
    "Milestone",
    "Progress",
    "earned",
    "progress_for",
    "rank_progress",
    "upcoming",
]
