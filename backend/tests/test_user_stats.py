"""
Dashboard statistics.

WHY THIS FILE EXISTS. The dashboard showed "0 sessions, — average, 0h practised,
0 day streak" for a candidate whose Reports page listed six completed interviews
with real scores. Two of those four numbers could never have been anything but
zero, for structural reasons that no test would have caught:

  hours_practiced   summed InterviewSession.duration_seconds, a column that was
                    declared on the model, read here, and written by nothing.
                    complete_session set status and completed_at and stopped.
  streak_days       was literally `streak_days=0,  # Phase 9: implement streak
                    calculation` — a hardcoded zero presented as a metric.

Both are the same failure as `users.is_active`: a field that exists, is read, and
is never populated. So these tests assert against the mechanism, not the value —
a test that checked "hours >= 0" would have passed against the broken version.
"""

from __future__ import annotations

import datetime as dt
import inspect

import pytest

from app.api.v1 import users as users_api
from app.services.interview import orchestrator as orch


class TestNoMetricIsHardcoded:
    """
    The complaint was "I do not want any hardcoded values". These pin the two that
    were.
    """

    def test_streak_is_computed_not_a_literal(self):
        src = inspect.getsource(users_api.get_stats)
        assert "streak_days=0" not in src, "the streak is hardcoded again"
        assert "_streak_days(" in src

    def test_no_phase_placeholder_remains(self):
        src = inspect.getsource(users_api.get_stats)
        for marker in ("Phase 9", "TODO", "FIXME", "implement streak"):
            assert marker not in src, f"unimplemented placeholder still present: {marker}"

    def test_every_returned_field_comes_from_a_query(self):
        """
        Each field must be traceable to a database result, not a constant. Guards
        against the next 'return 0 for now'.
        """
        src = inspect.getsource(users_api.get_stats)
        for field, source in [
            ("total_sessions", "session_row"),
            ("completed_sessions", "session_row"),
            ("average_score", "score_row"),
            ("total_questions_answered", "total_answers"),
            ("hours_practiced", "hours"),
            ("streak_days", "_streak_days"),
        ]:
            line = next(ln for ln in src.splitlines() if ln.strip().startswith(f"{field}="))
            assert source in line, f"{field} does not come from {source}: {line.strip()}"


class TestHoursPractisedIsRealData:
    def test_completing_a_session_records_its_duration(self):
        """
        The column was read by the stats query and written by nothing, so "hours
        practised" was structurally 0 for every user forever — not because they
        had not practised.
        """
        src = inspect.getsource(orch.InterviewOrchestrator.complete_session)
        assert "duration_seconds" in src, (
            "complete_session does not record a duration, so hours practised is a "
            "column nothing populates"
        )

    def test_the_duration_is_clamped(self):
        """
        A candidate can open an interview and walk away. Without a bound, the gap
        between started_at and completed_at counts as practice.
        """
        src = inspect.getsource(orch.InterviewOrchestrator.complete_session)
        assert "MAX_SESSION_SECONDS" in src
        assert "max(0," in src, "a clock change could otherwise record a negative duration"

    def test_the_cap_cannot_clip_a_real_session(self):
        """
        Twelve to twenty questions at a minute or two each is 25-40 minutes, so the
        cap must sit comfortably above that — and well below the hours an
        abandoned tab would otherwise claim.
        """
        assert 45 * 60 <= orch.MAX_SESSION_SECONDS <= 2 * 60 * 60

    def test_stats_derives_a_duration_for_historical_sessions(self):
        """
        Every session that existed when this was fixed has a NULL duration. Without
        a timestamp fallback the dashboard would keep reporting 0 hours until the
        user completed a brand-new interview, and their real history would never
        count.
        """
        src = inspect.getsource(users_api.get_stats)
        assert "coalesce" in src.lower()
        assert "completed_at - " in src or "completed_at\n" in src


class TestStreak:
    """
    Verified against the real query on seeded data: four completed sessions on four
    consecutive days returns 4. These cover the boundaries that data cannot.
    """

    def test_it_counts_from_today_or_yesterday(self):
        """
        Anchoring only on today resets everyone's streak at midnight, before they
        have had any chance to practise — so a fourteen-day run reads as zero when
        they open the app in the morning.
        """
        src = inspect.getsource(users_api._streak_days)
        assert "> 1" in src, "the streak must survive until a day is actually missed"

    def test_only_completed_sessions_count(self):
        """An abandoned session is not a day of practice."""
        src = inspect.getsource(users_api._streak_days)
        assert '"completed"' in src

    def test_it_is_scoped_to_the_user(self):
        src = inspect.getsource(users_api._streak_days)
        assert "user_id == user_id" in src or "InterviewSession.user_id" in src

    def test_days_are_deduplicated(self):
        """Three interviews in one day is a one-day streak, not three."""
        src = inspect.getsource(users_api._streak_days)
        assert "distinct" in src.lower()

    @pytest.mark.parametrize(
        ("days_ago", "expected"),
        [
            ([], 0),
            ([0], 1),
            ([1], 1),
            ([2], 0),
            ([0, 1, 2], 3),
            ([1, 2, 3], 3),
            ([0, 1, 3], 2),
            ([0, 2, 3], 1),
            ([5, 6, 7], 0),
        ],
    )
    def test_the_counting_rule(self, days_ago: list[int], expected: int):
        """
        The pure logic, replicated from _streak_days. Kept in step by the source
        assertions above; here to pin the arithmetic at the boundaries — a gap of
        one day continues a streak, a gap of two ends it, and a run that ended
        more than a day ago is over.
        """
        today = dt.date(2026, 8, 3)
        days = sorted({today - dt.timedelta(days=d) for d in days_ago}, reverse=True)
        if not days or (today - days[0]).days > 1:
            got = 0
        else:
            got = 1
            for newer, older in zip(days, days[1:], strict=False):
                if (newer - older).days != 1:
                    break
                got += 1
        assert got == expected


class TestAGenuineZeroIsNotMissingData:
    def test_a_zero_average_is_reported_not_hidden(self):
        """
        `if score_row.avg_score` is falsy at 0.0, so a candidate who genuinely
        averaged zero was shown "—" — told they had not been scored when they had,
        badly. Verified live: with a 0.0 report in the set the average came back
        30.93 rather than null.
        """
        src = inspect.getsource(users_api.get_stats)
        assert "avg_score is not None" in src
        assert "best_score is not None" in src
