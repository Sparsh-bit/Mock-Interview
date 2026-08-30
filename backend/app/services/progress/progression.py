"""
Not being asked again what you have already outgrown — services/progress/progression.py

TWO GAPS, BOTH ABOUT THE MOMENT A RETURNING CANDIDATE STARTS THEIR NEXT ROUND.

────────────────────────────────────────────────────────────────────────────────────────────
1. EVERY INTERVIEW STARTED FROM SCRATCH
────────────────────────────────────────────────────────────────────────────────────────────

`orchestrator._adaptive_signals` adapts beautifully WITHIN a session: the first scored answer
takes over and every question after it is pitched at the evidence. Before that first answer,
the only input is the self-rating the panel asks for — and its own docstring says why that is
safe: "an overclaim buys two hard questions and is then corrected by evidence".

That is exactly right for a first-time candidate and wrong for a returning one. Somebody who
has sat six rounds and holds a rating of 1700 has produced a great deal of evidence, and none
of it reached their seventh interview: they opened at "medium" like everyone else and spent
the first two questions being asked things they demonstrably outgrew four rounds ago. The
adaptive loop then corrected it, which means the cost is not a broken interview — it is two
of the twelve questions they paid for, every single time, forever.

`opening_difficulty` fixes that by answering with the LEDGER when the candidate has not said
anything, and with the CANDIDATE whenever they have.

THE PRECEDENCE IS THE SAME ONE `context.py` ARGUES FOR AT LENGTH: what the person actually
told us wins. The first draft of this had the ledger raising a low claim — so a candidate
rated 1700 who said "3, I'm shaky today" would have been handed hard questions anyway, on the
grounds that they had proven they could take them. That is the app telling somebody how they
feel, and it is wrong for the same reason reading the carrier track over the typed role was
wrong: a stated answer is evidence about right now, and a ledger is evidence about the past.

The existing design already tolerates this and says why — `_opening_signals_from_self_rating`
notes that "an overclaim buys two hard questions and is then corrected by evidence, and an
underclaim buys two easy ones and is corrected the same way". A claim of any kind is
self-correcting within two questions. What was never self-correcting was the DEFAULT, because
"medium" is not a claim about anybody: it was the answer for a first-timer and for somebody
six rounds in, permanently.

So:

  · a claim, high or low → exactly the claim, unchanged. First-timers and nervous returners
    are both completely unaffected by this function existing.
  · no claim → what they have proven, instead of a flat "medium" for everyone forever.
  · either way it is superseded by the first scored answer. This moves the starting point,
    never the adaptation.
  · it is derived from CLEARED rounds and rating, so it cannot be reached by buying credits.

────────────────────────────────────────────────────────────────────────────────────────────
2. NOWHERE TO PICK UP
────────────────────────────────────────────────────────────────────────────────────────────

An interview that was started and abandoned — a dropped connection, a flatmate, a battery —
leaves an ACTIVE session with answers in it and nothing anywhere pointing back to it. The
candidate returns to a dashboard that offers them a brand new interview, which costs another
credit and throws away the answers they already gave.

`resume_point` finds that session. It is a FACT, not a prompt: it says one exists and how far
in it got. Whether to show it, and how loudly, is the UI's business — and the answer there is
a line on a page somebody chose to open, never a message sent to them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.progress.rating import RANKS, Tier

#: Difficulty floors by rating. The bands line up with `rating.RANKS` on purpose — a candidate
#: told they are "Interview Ready" and then opened at the easiest tier is being contradicted by
#: the product in the same session.
#:
#: THREE VALUES, BECAUSE THE QUESTION MODEL HAS THREE. `Question.difficulty` is
#: easy | medium | hard, and inventing a finer scale here would be false precision that the
#: bank cannot honour.
_FLOOR_BY_RATING: list[tuple[int, str]] = [
    (1600, "hard"),
    (1350, "medium"),
    (0, "easy"),
]

#: Cleared rounds at a tier before that tier's evidence is taken as settled.
#:
#: TWO, NOT ONE. One cleared Core round is a good day; two is a level. This is the same
#: judgement `milestones.py` makes when it asks for three, and it is set lower here because
#: being asked a slightly-too-hard question costs a candidate far less than a milestone
#: awarded for a fluke.
_CLEARED_FOR_CONFIDENCE = 2


@dataclass(frozen=True, slots=True)
class ResumePoint:
    """An interview that was started and never finished."""

    session_id: uuid.UUID
    questions_answered: int
    #: How long ago it was abandoned, in hours. The UI decides what to do with that; this
    #: module does not decide that a nine-day-old session is "urgent", because it is not.
    hours_ago: int


def opening_difficulty(
    *,
    rating: int,
    cleared: dict[Tier, int],
    self_rating: int | None,
) -> str:
    """
    Where a returning candidate's questions should START — easy | medium | hard.

    WHAT THEY SAID WINS WHENEVER THEY SAID ANYTHING. The two inputs answer different
    questions — the ledger says what this candidate has PROVEN, the self-rating says how they
    feel TODAY — and when they disagree, the person is the one who knows. A candidate rated
    1700 who says "3, I'm shaky today" gets an easy opener; overriding that would be the app
    telling somebody how they feel, and it is self-correcting anyway, because the first scored
    answer takes over from question two.

    THE LEDGER ANSWERS THE DEFAULT, which is the case that was never self-correcting. "Medium"
    was the answer for a first-timer and for somebody six rounds in, permanently, because no
    claim means no evidence and the code had nowhere else to look. Now it looks here.
    """
    if self_rating is not None:
        return _self_rating_band(self_rating)

    floor = "easy"
    for threshold, level in _FLOOR_BY_RATING:
        if rating >= threshold:
            floor = level
            break

    # CLEARED ROUNDS CAN RAISE THE FLOOR THAT RATING ALONE WOULD NOT. A candidate who has
    # cleared two Panel rounds has demonstrated something a mid rating has not caught up with
    # yet — the rating is an average over their whole history and the cleared count is a
    # statement about their best, and for "what should we open with" the best is the better
    # evidence.
    if cleared.get(Tier.PANEL, 0) >= _CLEARED_FOR_CONFIDENCE:
        floor = "hard"
    elif cleared.get(Tier.CORE, 0) >= _CLEARED_FOR_CONFIDENCE and floor == "easy":
        floor = "medium"

    # NO EVIDENCE MEANS NO FLOOR. `BASE_RATING` is where everybody starts, so a rating at or
    # below it with nothing cleared says nothing at all about the candidate, and treating it
    # as a finding would pin every first-timer to "easy" — which is the same mistake in the
    # opposite direction.
    if not any(cleared.values()) and rating <= RANKS[1].floor:
        return "medium"

    return floor


def _self_rating_band(self_rating: int | None) -> str:
    """
    What the candidate asked for, out of ten, as a difficulty.

    Bands rather than a curve, matching `orchestrator._opening_signals_from_self_rating`
    exactly — two different mappings from the same number is two different interviews for the
    same answer, and the candidate has no way to tell which one they got.
    """
    if self_rating is None:
        return "medium"
    if self_rating >= 8:
        return "hard"
    if self_rating <= 4:
        return "easy"
    return "medium"


async def state_for(db, user_id: uuid.UUID) -> tuple[int, dict[Tier, int]]:
    """(rating, cleared-by-tier) — the two ledger facts `opening_difficulty` needs."""
    from app.services.progress.milestones import progress_for  # noqa: PLC0415

    progress = await progress_for(db, user_id)
    return progress.rating, progress.cleared


async def resume_point(db, user_id: uuid.UUID) -> ResumePoint | None:
    """
    The most recent interview this candidate started, answered something in, and left.

    None is the common answer and is not a failure. Never raises: this is read on a dashboard,
    and a dashboard that 500s because a resume hint could not be computed is a worse outcome
    than no hint.

    BOUNDED BY A WINDOW. An unfinished interview from three weeks ago is not something anybody
    is coming back to, and offering it reads as the app not having noticed that they moved on.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.session import InterviewSession, SessionStatus  # noqa: PLC0415
    from app.services.progress.streak import RESUME_WINDOW  # noqa: PLC0415

    cutoff = datetime.now(UTC) - RESUME_WINDOW
    row = (
        await db.execute(
            select(
                InterviewSession.id,
                InterviewSession.questions_asked,
                InterviewSession.started_at,
            )
            .where(
                InterviewSession.user_id == user_id,
                InterviewSession.status == SessionStatus.ACTIVE,
                # ANSWERED SOMETHING. An abandoned setup form is not a session worth
                # resuming — the same rule the dashboard's own counters apply, and the
                # difference between "you were half way through" and "you once opened a
                # form".
                InterviewSession.questions_asked > 0,
                InterviewSession.started_at.isnot(None),
                InterviewSession.started_at >= cutoff,
            )
            .order_by(InterviewSession.started_at.desc())
            .limit(1)
        )
    ).first()

    if row is None:
        return None
    session_id, answered, started = row
    elapsed = datetime.now(UTC) - (
        started if started.tzinfo else started.replace(tzinfo=UTC)
    )
    return ResumePoint(
        session_id=session_id,
        questions_answered=int(answered or 0),
        hours_ago=max(0, int(elapsed.total_seconds() // 3600)),
    )
