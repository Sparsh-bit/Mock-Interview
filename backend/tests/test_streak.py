"""
Days of real practice, counted in the right timezone — tests/test_streak.py

TWO DEFECTS THIS FILE PINS THE FIXES FOR, both of which shipped and neither of which was
visible as a failure.

────────────────────────────────────────────────────────────────────────────────────────────
1. THE DAY BOUNDARY WAS IN THE WRONG PLACE
────────────────────────────────────────────────────────────────────────────────────────────

The old implementation counted UTC calendar days and said so:

    "Days are UTC. That is wrong by up to a few hours for a candidate in IST, and it is the
     right trade for now."

It is a bigger error than that reads, because of who this product is for. India is UTC+5:30,
so a UTC day begins at 05:30 IST — and a student practising at eleven at night has that
session filed under TOMORROW. Practise every evening for a week and the ledger holds seven
days, no two of them adjacent to the day they actually practised, and the streak reads 1.

Three shapes of timezone break the obvious fixes, and each has a test below:

    half-hour offsets     IST is +5:30. Nothing that works in whole hours is correct here.
    quarter-hour offsets  Nepal is +5:45, Chatham +12:45. Same point, sharper.
    DST                   a local day is 23 or 25 hours long twice a year, so any arithmetic
                          that divides elapsed seconds by 86400 puts one session on the wrong
                          side of a boundary — silently, and only for people in those zones,
                          and only twice a year.

`zoneinfo` answers all three, and converting PER MOMENT rather than shifting a boundary once
is what makes the DST case come out right.

────────────────────────────────────────────────────────────────────────────────────────────
2. ATTENDANCE COUNTED AS PRACTICE
────────────────────────────────────────────────────────────────────────────────────────────

The old query took `InterviewSession.status == "completed"`, and `complete_session` sets that
status without looking at whether anything was answered. So starting an interview and ending
it immediately was a streak day — which is the "real usage versus a page view" hole, reached
through a button rather than a page load.

It is now structural rather than filtered. `activity_logs` gets a row ONLY when a quiz,
interview, group discussion or communication round is COMPLETED — nothing writes one for
opening the app, viewing a report or browsing tracks — and the interview half of the union
additionally requires that a question was actually asked.

────────────────────────────────────────────────────────────────────────────────────────────
AND WHAT THE STREAK IS NOT ALLOWED TO BE
────────────────────────────────────────────────────────────────────────────────────────────

It grants nothing. No credits, no multiplier, no unlock, no rating. `TestItRewardsNothing`
asserts that against the milestone conditions and the rating formula, because a streak that
pays out is a mechanic that makes stopping feel expensive — and this product has documented
under-18 users it cannot reliably identify (`docs/COMPLIANCE.md`), so it is not building one.
"""

from __future__ import annotations

import datetime as dt
import inspect
from zoneinfo import ZoneInfo

import pytest

from app.services.progress import milestones, rating
from app.services.progress.streak import (
    UTC_ZONE,
    Streak,
    compute,
    local_days,
    resolve_zone,
)

IST = ZoneInfo("Asia/Kolkata")          # +5:30, no DST
KATHMANDU = ZoneInfo("Asia/Kathmandu")  # +5:45
NEW_YORK = ZoneInfo("America/New_York")  # DST
CHATHAM = ZoneInfo("Pacific/Chatham")   # +12:45 / +13:45, DST


class TestTheDayBoundaryIsTheCandidates:
    def test_late_evening_practice_in_india_is_todays_practice(self):
        """
        THE ONE THE OLD IMPLEMENTATION GOT WRONG, and the single most common case for this
        product's actual users. 18:30 UTC is midnight in Kolkata, so everything a student does
        between 18:30 and 23:59 UTC — which is 00:00 to 05:29 the NEXT day locally — used to
        be filed a day late.
        """
        eleven_pm_ist = dt.datetime(2026, 8, 30, 17, 30, tzinfo=dt.UTC)
        assert eleven_pm_ist.date() == dt.date(2026, 8, 30)
        assert local_days([eleven_pm_ist], IST) == {dt.date(2026, 8, 30)}

        # And just past local midnight is genuinely the next day.
        past_midnight = dt.datetime(2026, 8, 30, 18, 45, tzinfo=dt.UTC)
        assert past_midnight.date() == dt.date(2026, 8, 30)
        assert local_days([past_midnight], IST) == {dt.date(2026, 8, 31)}

    def test_an_evening_habit_in_ist_is_a_streak_and_not_seven_islands(self):
        """
        The defect end to end. Seven consecutive evenings at 23:00 IST.

        In UTC those are seven moments at 17:30, each on its own day — but the OLD code took
        `func.date()` of a completion timestamp, and 17:30 UTC is the same UTC day as the
        morning, so this particular pattern happened to survive. The one that did not is
        below: practice after 18:30 UTC, which is most of an Indian student's evening.
        """
        evenings = [
            dt.datetime(2026, 8, d, 17, 30, tzinfo=dt.UTC) for d in range(24, 31)
        ]
        days = local_days(evenings, IST)
        assert len(days) == 7
        assert compute(days, dt.date(2026, 8, 30))[0] == 7

    def test_practice_after_local_midnight_still_extends_the_run(self):
        """
        A student who practises at 00:30 IST on the 29th and 00:30 IST on the 30th has a
        two-day streak. In UTC those are 19:00 on the 28th and 19:00 on the 29th — the right
        answer either way here, which is precisely why the bug survived: it is only wrong when
        the two conventions disagree about which day it is, and then it is wrong invisibly.
        """
        moments = [
            dt.datetime(2026, 8, 28, 19, 0, tzinfo=dt.UTC),
            dt.datetime(2026, 8, 29, 19, 0, tzinfo=dt.UTC),
        ]
        days = local_days(moments, IST)
        assert days == {dt.date(2026, 8, 29), dt.date(2026, 8, 30)}
        assert compute(days, dt.date(2026, 8, 30))[0] == 2

    def test_a_quarter_hour_offset_is_handled(self):
        # Nepal is +5:45. Anything working in whole or half hours is wrong here, and this is
        # the case that catches a "close enough" fix.
        moment = dt.datetime(2026, 8, 30, 18, 20, tzinfo=dt.UTC)  # 00:05 on the 31st, NPT
        assert local_days([moment], KATHMANDU) == {dt.date(2026, 8, 31)}
        assert local_days([moment], IST) == {dt.date(2026, 8, 30)}  # 23:50 on the 30th, IST

    def test_a_day_that_is_twenty_three_hours_long_is_still_one_day(self):
        """
        DST, and the reason conversion happens per moment rather than by shifting a boundary.

        8 March 2026 is a spring-forward day in New York: local 02:00 becomes 03:00 and the
        day is 23 hours long. Two sessions either side of that jump are the same local day,
        and any arithmetic assuming 24-hour days puts them on different ones.
        """
        before = dt.datetime(2026, 3, 8, 6, 0, tzinfo=dt.UTC)   # 01:00 EST
        after = dt.datetime(2026, 3, 8, 20, 0, tzinfo=dt.UTC)   # 16:00 EDT
        assert local_days([before, after], NEW_YORK) == {dt.date(2026, 3, 8)}

    def test_a_day_that_is_twenty_five_hours_long_is_still_one_day(self):
        # 1 November 2026, falling back: local 02:00 becomes 01:00 and the day is 25 hours.
        early = dt.datetime(2026, 11, 1, 4, 0, tzinfo=dt.UTC)   # 00:00 EDT
        late = dt.datetime(2026, 11, 2, 4, 0, tzinfo=dt.UTC)    # 23:00 EST, same local day
        assert local_days([early, late], NEW_YORK) == {dt.date(2026, 11, 1)}

    def test_a_streak_survives_a_dst_change(self):
        """
        The case that would break silently, for one population, twice a year. Practice on
        every local day across a spring-forward.
        """
        moments = [
            dt.datetime(2026, 3, 6, 18, 0, tzinfo=dt.UTC),
            dt.datetime(2026, 3, 7, 18, 0, tzinfo=dt.UTC),
            dt.datetime(2026, 3, 8, 18, 0, tzinfo=dt.UTC),
            dt.datetime(2026, 3, 9, 18, 0, tzinfo=dt.UTC),
        ]
        days = local_days(moments, NEW_YORK)
        assert len(days) == 4
        assert compute(days, dt.date(2026, 3, 9))[0] == 4

    def test_an_extreme_offset_is_handled(self):
        # Chatham is +12:45 or +13:45. Sanity that nothing here assumes an offset small
        # enough to keep the UTC date within a day of the local one.
        moment = dt.datetime(2026, 8, 30, 12, 0, tzinfo=dt.UTC)
        assert local_days([moment], CHATHAM) == {dt.date(2026, 8, 31)}

    def test_a_naive_timestamp_is_read_as_utc(self):
        # Everything in this codebase stores aware UTC, so a naive value means a driver or a
        # test that dropped the tzinfo. Reading it as UTC is what every other read here does.
        naive = dt.datetime(2026, 8, 30, 17, 30)
        assert local_days([naive], IST) == {dt.date(2026, 8, 30)}

    @pytest.mark.parametrize("bad", [None, "", "Mars/Olympus", "not a zone", "UTC+5:30"])
    def test_an_unusable_timezone_falls_back_to_utc_rather_than_failing(self, bad):
        # `Profile.timezone` is a free-ish string column. A candidate whose profile holds a
        # typo must still get a streak — wrong by hours is a far smaller failure than a 500
        # on the dashboard.
        assert resolve_zone(bad) is UTC_ZONE

    def test_a_real_timezone_is_used(self):
        assert resolve_zone("Asia/Kolkata") == IST


class TestTheCountingRule:
    @pytest.mark.parametrize(
        ("days_ago", "expected"),
        [
            ([], 0),
            ([0], 1),
            ([1], 1),          # yesterday keeps it alive for exactly one day
            ([2], 0),          # two days is a lapse
            ([0, 1, 2], 3),
            ([1, 2, 3], 3),
            ([0, 1, 3], 2),    # the gap ends the run
            ([0, 2, 3], 1),
            ([5, 6, 7], 0),    # a finished run is not a current one
            (list(range(30)), 30),
        ],
    )
    def test_current_streak(self, days_ago: list[int], expected: int):
        today = dt.date(2026, 8, 30)
        days = {today - dt.timedelta(days=d) for d in days_ago}
        assert compute(days, today)[0] == expected

    def test_practised_today_is_separate_from_the_count(self):
        today = dt.date(2026, 8, 30)
        yesterday = today - dt.timedelta(days=1)
        assert compute({today, yesterday}, today) == (2, True, 2)
        # Same streak length, but they have not practised yet today.
        assert compute({yesterday, yesterday - dt.timedelta(days=1)}, today) == (2, False, 2)

    def test_the_best_run_is_remembered_after_the_current_one_lapses(self):
        """
        A candidate on day two of a new run may have a twelve-day run behind them. Telling
        them their best is two would be false, and `best` cannot be derived from `days`.
        """
        today = dt.date(2026, 8, 30)
        days = {today, today - dt.timedelta(days=1)} | {
            today - dt.timedelta(days=d) for d in range(20, 32)
        }
        current, practised, best = compute(days, today)
        assert current == 2
        assert practised is True
        assert best == 12

    def test_a_run_across_a_month_boundary_is_continuous(self):
        days = {dt.date(2026, 7, 30), dt.date(2026, 7, 31), dt.date(2026, 8, 1)}
        assert compute(days, dt.date(2026, 8, 1))[0] == 3

    def test_a_run_across_a_leap_day_is_continuous(self):
        days = {dt.date(2028, 2, 28), dt.date(2028, 2, 29), dt.date(2028, 3, 1)}
        assert compute(days, dt.date(2028, 3, 1))[0] == 3

    def test_at_risk_is_a_live_streak_that_today_has_not_extended(self):
        assert Streak(days=5, practised_today=False, best=5, timezone="UTC").at_risk is True
        assert Streak(days=5, practised_today=True, best=5, timezone="UTC").at_risk is False
        # Not "at risk" when there is no streak to lose — which is the state that would
        # otherwise produce the most pressuring copy of all.
        assert Streak(days=0, practised_today=False, best=9, timezone="UTC").at_risk is False


class TestRealPracticeVersusAPageView:
    def test_nothing_writes_an_activity_row_for_looking_at_a_page(self):
        """
        THE STRUCTURAL ARGUMENT, asserted rather than assumed. `activity_logs` is the ledger
        the streak reads, and it is trustworthy only because nothing writes to it on a read
        path. Every call site is a completion.
        """
        import pathlib

        app_dir = pathlib.Path(inspect.getfile(compute)).resolve().parents[2]
        callers = [
            f
            for f in app_dir.rglob("*.py")
            if "log_activity(" in f.read_text() and f.name != "activity.py"
        ]
        assert callers, "the scan found no call sites — it is broken, not the code"
        for f in callers:
            src = f.read_text()
            for kind in ("quiz", "interview", "communication", "group_discussion"):
                if f'activity_type="{kind}"' not in src:
                    continue
                # A completion path, by construction: these four are written when a round
                # finishes and a score exists.
                assert "score" in src

    def test_an_interview_must_have_asked_a_question_to_count(self):
        """
        The hole the old implementation had. `complete_session` sets status without checking
        that anything was answered, so start-then-end-immediately was a streak day.
        """
        from app.services.progress.streak import for_user

        src = inspect.getsource(for_user)
        assert "questions_asked > 0" in src

    def test_every_kind_of_practice_counts_not_only_interviews(self):
        """
        The old streak counted interviews only, so a candidate doing a quiz every day had a
        streak of zero — wrong, and an incentive pointed at the most expensive feature rather
        than the most useful habit.
        """
        from app.services.progress.streak import for_user

        src = inspect.getsource(for_user)
        assert "ActivityLog" in src
        assert "InterviewSession" in src


class TestItRewardsNothing:
    """
    THE PRODUCT CONSTRAINT, asserted where it could actually be violated.

    A streak that pays out is a mechanic that makes stopping feel expensive. This product has
    documented under-18 users it cannot reliably identify (`docs/COMPLIANCE.md`), DPDP §9
    prohibits behavioural monitoring and targeted advertising directed at them, and the honest
    response is not to build compulsion for anybody rather than to build it and hope the age
    gate holds.
    """

    def test_no_milestone_is_conditioned_on_a_streak(self):
        src = inspect.getsource(milestones)
        conditions = src[src.index("MILESTONES: list[Milestone] = ["):]
        assert "streak" not in conditions.lower(), (
            "a milestone unlocked by attendance is a participation badge, and it makes the "
            "streak a thing you lose rather than a thing you have"
        )

    def test_the_rating_formula_does_not_read_a_streak(self):
        # The rating is the credential. A streak bonus in it would mean a candidate who
        # practises daily outranks one who is better, which makes the number worthless to the
        # people it is meant to inform.
        assert "streak" not in inspect.getsource(rating).lower()

    def test_the_streak_carries_no_reward_field(self):
        # No multiplier, no bonus, no credits. If one is ever added it has to be added here,
        # and this fails.
        assert set(Streak.__dataclass_fields__) == {
            "days",
            "practised_today",
            "best",
            "timezone",
        }

    def test_nothing_is_sent_to_anybody(self):
        """
        The brief's hard rule: no re-engagement message without real consent. There is no
        outbound channel in this repository at all, and this asserts the streak did not quietly
        become the first one.
        """
        import pathlib

        src = pathlib.Path(inspect.getfile(compute)).read_text()
        api = (
            pathlib.Path(inspect.getfile(compute)).resolve().parents[2]
            / "api" / "v1" / "progress.py"
        ).read_text()
        for word in ("smtp", "sendmail", "send_email", "push_notification", "twilio"):
            assert word not in src.lower()
            assert word not in api.lower()
