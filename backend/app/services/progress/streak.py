"""
Consecutive days of real practice — services/progress/streak.py

WHAT WAS HERE BEFORE, AND WHAT WAS WRONG WITH IT. `api/v1/users._streak_days` computed this
inline and its own docstring named the first defect:

    "Days are UTC. That is wrong by up to a few hours for a candidate in IST, and it is the
     right trade for now."

It was a reasonable trade to defer and it is the wrong one to keep, because of who this
product is for. India is UTC+5:30, so a UTC calendar day begins at 05:30 IST — and a student
practising at 11pm has that session filed under TOMORROW. Practise every night at eleven for
a week and the UTC ledger shows seven days, each holding one session, with no two of them
adjacent to the day you actually practised. The streak is not a few hours out; for the
population that uses this app most, it is systematically attributing evening practice to the
wrong day.

Half-hour and quarter-hour offsets are why this cannot be fixed with an hours-offset
subtraction: IST is +5:30, Nepal +5:45, Chatham +12:45. And a DST-observing zone has days
that are 23 or 25 hours long, so "divide by 86400" is wrong twice a year in exactly the way
that silently breaks a streak somebody has been keeping. `zoneinfo` is in the standard library
and answers all three correctly.

THE SECOND DEFECT WAS QUIETER AND WORSE. The old query counted
`InterviewSession.status == "completed"`, and `complete_session` sets that status without
looking at whether anything was answered. So START-then-END-IMMEDIATELY was a streak day. The
same file defines `_real_session()` — "an abandoned plan is not practice: nothing was asked,
nothing was answered" — twenty lines below, and the streak did not use it.

It also counted interviews ONLY. A candidate doing a quiz every day and a group discussion at
the weekend had a streak of zero, which is both wrong and an incentive pointed at the most
expensive feature rather than the most useful habit.

────────────────────────────────────────────────────────────────────────────────────────────
WHAT COUNTS AS A DAY OF PRACTICE
────────────────────────────────────────────────────────────────────────────────────────────

A day on which the candidate finished something. Concretely, either:

  · a row in `activity_logs` — written ONLY on completion of a quiz, an interview, a group
    discussion or a communication round. Nothing writes a row for opening the app, viewing a
    report or browsing tracks, so "real practice, not a page view" is STRUCTURAL here rather
    than a filter that has to be maintained; or
  · an `InterviewSession` that satisfies the same "real session" rule the dashboard's own
    counters use — questions actually asked. This is the union because `activity_logs` gets
    its interview row when the REPORT is generated, and a candidate who sits a full interview
    and never opens the report has still practised.

DELIBERATELY NOT A REWARD, AND THIS IS A PRODUCT CONSTRAINT RATHER THAN A STYLE NOTE. The
streak grants nothing — no credits, no multiplier, no unlock, no rating. It is a count of
days, reported. That rules out the mechanic where a number that pays out makes stopping feel
expensive, which is the shape this product must not have: DPDP §9 forbids behavioural
monitoring and targeted advertising directed at under-18s, and while signup now asks for an
18+ declaration, `docs/COMPLIANCE.md` records that the gate has a window and that "doing
neither is the current position". A mechanic that only works because somebody is afraid to
lose it is one this product should not be building for adults either.

For the same reason there is no streak freeze, no streak repair, and no notification. A
lapsed streak simply reads zero, which is true, and the candidate can start another one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

logger = structlog.get_logger(__name__)

UTC_ZONE = ZoneInfo("UTC")


@dataclass(frozen=True, slots=True)
class Streak:
    """Consecutive days of real practice, in the candidate's own timezone."""

    #: Days in a row, ending today or yesterday. Zero when the run has lapsed.
    days: int
    #: Has the candidate practised on their own today? Drives an honest sentence in the UI —
    #: "you have practised today" versus "practise today to keep it" — and nothing else.
    practised_today: bool
    #: The longest run ever, which is a fact about them rather than a target set for them.
    best: int
    #: The zone the days were counted in, so a candidate who thinks the number is wrong can be
    #: told what it was computed against rather than argued with.
    timezone: str

    @property
    def at_risk(self) -> bool:
        """
        A live streak that today has not yet extended.

        STATED, NEVER COUNTED DOWN. This is the flag most likely to be turned into a timer, a
        red banner or an evening push notification, and it must not be any of those: it exists
        so the UI can say what is true when the candidate is already looking at the page. See
        the module docstring on why this product does not build urgency.
        """
        return self.days > 0 and not self.practised_today


def local_days(moments: list[datetime], zone: ZoneInfo) -> set[date]:
    """
    The distinct local calendar days these moments fall on.

    CONVERTED PER MOMENT rather than by shifting a date boundary once, which is what makes
    this correct across a DST change: a local day is 23 or 25 hours long twice a year, and any
    arithmetic that assumes 24 puts one session on the wrong side of a boundary.

    A naive datetime is read as UTC. Everything in this codebase stores timezone-aware UTC —
    `TimestampMixin` uses `timezone=True` — so a naive value means a driver or a test that
    dropped the tzinfo, and treating it as UTC is what every other read here already does.
    """
    days: set[date] = set()
    for moment in moments:
        aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC_ZONE)
        days.add(aware.astimezone(zone).date())
    return days


def resolve_zone(name: str | None) -> ZoneInfo:
    """
    The candidate's timezone, or UTC when it is missing or unrecognised.

    NEVER RAISES. `Profile.timezone` is a free-ish string column with a default of "UTC", and
    a candidate whose profile holds a typo must still get a streak — a wrong-by-hours number
    is a much smaller failure than a 500 on the dashboard. Logged, because a zone nobody can
    resolve is worth knowing about and is invisible otherwise.
    """
    if not name:
        return UTC_ZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("streak_unknown_timezone", timezone=name[:64])
        return UTC_ZONE


def compute(practice_days: set[date], today: date) -> tuple[int, bool, int]:
    """
    (current streak, practised today, best ever) from the set of local practice days.

    PURE, AND SEPARATED FROM THE QUERY ON PURPOSE. Every interesting case here is about
    calendars — a gap, a lapse, a run across a month boundary, a run across a DST change — and
    none of them needs a database to state. `tests/test_streak.py` is almost entirely calls to
    this function.

    THE RUN MAY END TODAY OR YESTERDAY. Anchoring only on today would reset everybody's streak
    at local midnight, before they have had any chance to practise, so somebody with a
    fortnight's run would open the app over breakfast and be told zero. Yesterday keeps it
    alive for exactly one day, which is the length of the chance they are being given.
    """
    if not practice_days:
        return 0, False, 0

    ordered = sorted(practice_days, reverse=True)
    practised_today = today in practice_days

    current = 0
    if (today - ordered[0]).days <= 1:
        current = 1
        for newer, older in zip(ordered, ordered[1:], strict=False):
            if (newer - older).days != 1:
                break
            current += 1

    # The best run ever, which is a different question from the current one and cannot be
    # derived from it: a candidate on day two of a new run may have a twelve-day run behind
    # them, and telling them their best is two would be false.
    best = 1
    run = 1
    for newer, older in zip(ordered, ordered[1:], strict=False):
        run = run + 1 if (newer - older).days == 1 else 1
        best = max(best, run)

    return current, practised_today, best


async def for_user(db, user_id: uuid.UUID) -> Streak:
    """
    The candidate's streak, counted in their own timezone.

    ONE QUERY PER SOURCE AND THEN ARITHMETIC IN PYTHON, rather than `func.date()` in SQL. The
    database has no idea what timezone this candidate is in, and pushing the conversion into
    SQL would either hardcode UTC — the bug being fixed — or need the zone interpolated into
    the query, which is both awkward and a place for a zone name to reach SQL as text.
    """
    from sqlalchemy import or_, select  # noqa: PLC0415

    from app.models.activity import ActivityLog  # noqa: PLC0415
    from app.models.session import InterviewSession  # noqa: PLC0415
    from app.models.user import Profile  # noqa: PLC0415

    zone_name = await db.scalar(select(Profile.timezone).where(Profile.user_id == user_id))
    zone = resolve_zone(zone_name)

    # Completed activities of every kind. Nothing writes here for a page view.
    activity_moments = list(
        await db.scalars(select(ActivityLog.created_at).where(ActivityLog.user_id == user_id))
    )

    # Plus interviews that were really sat, whether or not a report was ever generated. The
    # SAME rule the dashboard's counters use — see `users._real_session` — rather than a
    # second opinion about what practice is.
    session_moments = list(
        await db.scalars(
            select(InterviewSession.completed_at).where(
                InterviewSession.user_id == user_id,
                InterviewSession.completed_at.isnot(None),
                or_(
                    InterviewSession.questions_asked > 0,
                    InterviewSession.status == "completed",
                ),
                # THE HOLE THE OLD STREAK HAD. `complete_session` sets the status without
                # looking at whether anything was answered, so start-then-end-immediately was
                # a streak day. Requiring a question to have been asked is what makes this
                # practice rather than attendance.
                InterviewSession.questions_asked > 0,
            )
        )
    )

    days = local_days([m for m in activity_moments + session_moments if m is not None], zone)
    today = datetime.now(UTC_ZONE).astimezone(zone).date()
    current, practised_today, best = compute(days, today)
    return Streak(
        days=current,
        practised_today=practised_today,
        best=best,
        timezone=str(zone),
    )


#: How far back "recently" reaches when looking for somewhere to pick up. Two weeks, because
#: an unfinished interview older than that is not something anybody is coming back to — they
#: have moved on, and offering it reads as the app not having noticed.
RESUME_WINDOW = timedelta(days=14)
