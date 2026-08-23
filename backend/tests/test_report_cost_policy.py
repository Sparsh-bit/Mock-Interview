"""
Tests for the report generation cost policy — api/v1/reports.should_regenerate.

This function decides whether opening a report costs money. The report page
requests generation on every view, so a wrong answer here is not a cosmetic bug:
returning True for an already-scored report would re-bill a Claude call on every
page load, which is how a single interview previously cost $2.

Pure function, no database or provider needed — these run anywhere.
"""

from __future__ import annotations

import pytest

from app.api.v1.reports import (
    _MAX_UNSCORED_ATTEMPTS,
    _REPORT_TOKENS_MAX,
    _UNSCORED,
    report_token_budget,
    should_regenerate,
)


class TestTokenBudgetFitsTheReport:
    """
    The regression guard for the bug that broke every long interview.

    A flat max_tokens of 2600, clamped to 4096 by the provider, against a measured
    requirement of ~5078 output tokens for a 16-question report: the JSON was cut
    mid-object, validation rejected it, and the candidate got an unscored
    placeholder. Truncation has no partial credit — one token short loses the whole
    report AND still bills for the tokens.
    """

    #: Measured against the live API for a 16-question session.
    MEASURED_16Q = 5078

    def test_sixteen_question_report_fits_with_headroom(self):
        budget = report_token_budget(16)
        assert budget >= self.MEASURED_16Q, (
            f"budget {budget} is below the measured {self.MEASURED_16Q} tokens a "
            "16-question report needs — reports will truncate and score 0"
        )

    def test_the_provider_ceiling_does_not_clamp_a_legitimate_report(self):
        """
        The bug had TWO ceilings. Raising the call site alone did nothing, because
        ANTHROPIC_MAX_OUTPUT_TOKENS clamped it afterwards. This asserts the global
        ceiling stays above the largest budget a report can ask for — otherwise the
        clamp silently truncates again and the call-site budget is a lie.
        """
        from app.core.config import Settings

        ceiling = Settings.model_fields["ANTHROPIC_MAX_OUTPUT_TOKENS"].default
        assert ceiling >= _REPORT_TOKENS_MAX, (
            f"ANTHROPIC_MAX_OUTPUT_TOKENS default ({ceiling}) is below the largest "
            f"report budget ({_REPORT_TOKENS_MAX}); the provider would clamp and "
            "truncate the response"
        )

    def test_budget_grows_with_the_interview(self):
        # The whole point: one constant cannot serve both a short and a long
        # interview, because question_analysis carries one entry per question.
        assert report_token_budget(6) < report_token_budget(16)

    def test_short_interview_is_not_charged_for_a_long_one(self):
        # Scaling must actually save money on the common case, or it is pointless.
        assert report_token_budget(6) < _REPORT_TOKENS_MAX

    def test_a_session_with_no_answers_still_gets_the_summary_sections(self):
        assert report_token_budget(0) > 0

    @pytest.mark.parametrize("count", [-5, 0, 1, 12, 16, 20, 50, 10_000])
    def test_budget_is_always_positive_and_bounded(self, count: int):
        budget = report_token_budget(count)
        assert 0 < budget <= _REPORT_TOKENS_MAX


def _placeholder(attempts: int | None = None) -> dict:
    raw: dict = {"generated_by": _UNSCORED}
    if attempts is not None:
        raw["unscored_attempts"] = attempts
    return raw


class TestScoredReportsAreNeverRebilled:
    """The money-critical case: a finished report must be free to re-read."""

    def test_ai_generated_report_is_not_regenerated(self):
        regenerate, _ = should_regenerate({"generated_by": "ai", "overall_score": 72})
        assert regenerate is False

    def test_any_non_placeholder_marker_is_treated_as_final(self):
        # Unknown provenance is still not the placeholder, so it is a real report.
        regenerate, _ = should_regenerate({"generated_by": "some_future_pipeline"})
        assert regenerate is False

    def test_report_with_no_marker_is_treated_as_final(self):
        # Rows written before the marker existed must not all start re-billing.
        assert should_regenerate({}) == (False, 0)


class TestPlaceholdersAreRetried:
    """An unscored placeholder tells the user to retry, so retrying must work."""

    def test_placeholder_with_no_counter_is_retried(self):
        regenerate, attempts = should_regenerate(_placeholder())
        assert regenerate is True
        assert attempts == 0

    @pytest.mark.parametrize("attempts", range(_MAX_UNSCORED_ATTEMPTS))
    def test_placeholder_under_the_cap_is_retried(self, attempts: int):
        regenerate, seen = should_regenerate(_placeholder(attempts))
        assert regenerate is True
        assert seen == attempts


class TestRetriesAreBounded:
    """A provider outage must not become an unbounded bill."""

    def test_placeholder_at_the_cap_stops_retrying_within_the_cooldown(self):
        # Same change as the test below: a fresh timestamp is what the cap refuses. Without one
        # the row reads as pre-dating the field, which now means it is retried.
        from datetime import UTC, datetime

        raw = _placeholder(_MAX_UNSCORED_ATTEMPTS)
        raw["unscored_last_at"] = datetime.now(UTC).isoformat()
        regenerate, attempts = should_regenerate(raw)
        assert regenerate is False
        assert attempts == _MAX_UNSCORED_ATTEMPTS

    def test_placeholder_over_the_cap_stops_retrying_within_the_cooldown(self):
        """
        The cap still holds — it just holds for a WINDOW rather than forever.

        This used to pass a placeholder with no timestamp, which now means "written before the
        field existed, therefore old, therefore retry". A fresh timestamp is what a reload storm
        actually looks like, and that is the case the cap exists to refuse.
        """
        from datetime import UTC, datetime

        raw = _placeholder(_MAX_UNSCORED_ATTEMPTS + 50)
        raw["unscored_last_at"] = datetime.now(UTC).isoformat()
        regenerate, _ = should_regenerate(raw)
        assert regenerate is False

    def test_cap_is_small_enough_to_bound_spend(self):
        # Guards the constant itself: this many billed calls happen per failing
        # session, so a careless bump is a cost regression.
        assert 1 <= _MAX_UNSCORED_ATTEMPTS <= 5


class TestHostileStoredData:
    """raw_report is JSONB — it can contain anything a past version wrote."""

    def test_none_is_treated_as_no_report(self):
        assert should_regenerate(None) == (False, 0)

    @pytest.mark.parametrize("bad", ["3", None, -1, 2.7, [], {}, float("nan")])
    def test_non_integer_counter_falls_back_to_zero_not_a_crash(self, bad):
        # A crash here would 500 the report page; treating it as a first attempt
        # is the safe reading, and the cap still applies from there on.
        regenerate, attempts = should_regenerate(
            {"generated_by": _UNSCORED, "unscored_attempts": bad}
        )
        assert regenerate is True
        assert attempts == 0

    def test_boolean_counter_is_not_mistaken_for_an_int(self):
        # bool is a subclass of int in Python; True must not read as "1 attempt"
        # in a way that silently changes the budget. Either reading is bounded,
        # so simply assert it stays within the cap and does not crash.
        regenerate, attempts = should_regenerate(
            {"generated_by": _UNSCORED, "unscored_attempts": True}
        )
        assert regenerate is True
        assert 0 <= attempts < _MAX_UNSCORED_ATTEMPTS


class TestAnExhaustedReportRecoversInsteadOfDying:
    """
    THE ROOT CAUSE OF "REPORT PENDING" FOREVER.

    `should_regenerate` used to return `attempts < _MAX_UNSCORED_ATTEMPTS` and nothing else, so
    three failures were PERMANENT: the endpoint then served the placeholder straight from the
    database with no model call. "Generate again" did nothing, the score sat at 0/100 for good,
    and because an unscored report is deliberately never paywalled, the unlock could never
    appear either — one transient failure took away both the report and the sale.

    Every interview that hit the earlier report timeouts burned its three attempts and was then
    dead. That is a whole cohort of reports that could not be produced by any action available
    to the candidate or the operator.

    The cap stays, because repeated page views must not fund an open-ended bill against a model
    that is failing. What changed is that it AGES: a reload storm is the expensive case and it
    happens in seconds, so a cooldown stops it just as effectively while letting a session
    recover once whatever broke has passed.
    """

    def _exhausted(self, *, minutes_ago: float) -> dict:
        from datetime import UTC, datetime, timedelta

        return {
            "generated_by": _UNSCORED,
            "unscored_attempts": _MAX_UNSCORED_ATTEMPTS,
            "unscored_last_at": (
                datetime.now(UTC) - timedelta(minutes=minutes_ago)
            ).isoformat(),
        }

    def test_it_still_refuses_a_reload_storm(self):
        # Seconds after the third failure — somebody holding the retry button. This is the
        # case the cap exists for and it must still be refused.
        regenerate, attempts = should_regenerate(self._exhausted(minutes_ago=0))
        assert regenerate is False
        assert attempts == _MAX_UNSCORED_ATTEMPTS

    def test_it_retries_once_the_cooldown_has_passed(self):
        from app.core.config import settings

        aged = settings.REPORT_UNSCORED_RETRY_COOLDOWN_MINUTES + 1
        regenerate, attempts = should_regenerate(self._exhausted(minutes_ago=aged))
        assert regenerate is True, "an exhausted report can never recover"
        # RESET, not one grudging extra try: a fresh set of attempts, so a session that broke
        # during an outage gets the same chance as one that never failed.
        assert attempts == 0

    def test_a_placeholder_from_before_the_timestamp_existed_is_retried(self):
        """
        THE INVERSE OF WHAT THIS ASSERTED, AND THE CHANGE IS THE POINT.

        It used to refuse, on the reasoning that unknown age should not be read as "old
        enough". That was wrong in the one way that mattered: every report ALREADY broken when
        the cooldown shipped carries no timestamp, so refusing them meant the fix rescued
        nobody who was already affected — the entire population it was written for.

        A missing timestamp is not unknown age. It means the row predates the deploy that began
        writing the field, so it is necessarily older than any cooldown. The reload-storm risk
        is one extra attempt per legacy report, because the retry stamps a real timestamp and
        every decision after that is made on actual age.
        """
        regenerate, attempts = should_regenerate(
            {"generated_by": _UNSCORED, "unscored_attempts": _MAX_UNSCORED_ATTEMPTS}
        )
        assert regenerate is True, "already-broken reports stay broken forever"
        assert attempts == 0

    def test_a_corrupt_timestamp_retries_rather_than_crashing_or_stranding(self):
        """
        Two things at once, and both matter.

        `raw_report` is JSONB and can hold anything a past version wrote, so an unparseable
        value must not raise — a ValueError here would 500 the report page.

        And it must not refuse either. Refusing on garbage strands exactly the rows whose
        history we cannot read, permanently, for a data problem that is ours rather than the
        candidate's. The retry overwrites the field with a valid timestamp, so this can happen
        at most once per row.
        """
        for bad in ("not a date", "", 12345, [], {}, None):
            regenerate, attempts = should_regenerate(
                {
                    "generated_by": _UNSCORED,
                    "unscored_attempts": _MAX_UNSCORED_ATTEMPTS,
                    "unscored_last_at": bad,
                }
            )
            assert regenerate is True, f"{bad!r} stranded the report"
            assert attempts == 0

    def test_a_real_scored_report_is_never_regenerated_however_old(self):
        # The cooldown must not start re-billing finished reports — generation is called on
        # every page view, so that would be a bill funded by ordinary reading.
        from datetime import UTC, datetime, timedelta

        regenerate, _ = should_regenerate(
            {
                "generated_by": "ai",
                "unscored_attempts": 99,
                "unscored_last_at": (datetime.now(UTC) - timedelta(days=30)).isoformat(),
            }
        )
        assert regenerate is False

    def test_the_attempt_time_is_actually_written(self):
        # Without it nothing can be aged, and the cooldown silently never triggers — the
        # permanent-pending bug, back with a setting that looks like it should have fixed it.
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/reports.py"
        ).read_text()
        assert '"unscored_last_at": datetime.now(UTC).isoformat()' in src

    def test_the_cooldown_can_be_switched_off(self):
        from app.core.config import settings

        original = settings.REPORT_UNSCORED_RETRY_COOLDOWN_MINUTES
        try:
            settings.REPORT_UNSCORED_RETRY_COOLDOWN_MINUTES = 0
            regenerate, _ = should_regenerate(self._exhausted(minutes_ago=10_000))
            assert regenerate is False, "zero must restore the permanent cap"
        finally:
            settings.REPORT_UNSCORED_RETRY_COOLDOWN_MINUTES = original
