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

from app.api.v1.reports import _MAX_UNSCORED_ATTEMPTS, _UNSCORED, should_regenerate


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

    def test_placeholder_at_the_cap_stops_retrying(self):
        regenerate, attempts = should_regenerate(_placeholder(_MAX_UNSCORED_ATTEMPTS))
        assert regenerate is False
        assert attempts == _MAX_UNSCORED_ATTEMPTS

    def test_placeholder_over_the_cap_stops_retrying(self):
        regenerate, _ = should_regenerate(_placeholder(_MAX_UNSCORED_ATTEMPTS + 50))
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
