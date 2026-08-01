"""
Tests for the campus recruiter catalogue and roadmap generator.

The catalogue is a hand-edited YAML file, so these are mostly guards against the
mistakes a human makes editing YAML at 2am — a weight that no longer sums to 100,
a duplicated slug, a company with no topics. Each of those produces a roadmap that
still *renders*, just wrong, which is the worst kind of bug: it looks like a
working feature while quietly telling a candidate to study the wrong things.

Pure functions over a file. No database, no network.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.prep import build_roadmap, get_company, load_catalogue
from app.services.prep.catalogue import Company

CATALOGUE = load_catalogue()


class TestCatalogueIntegrity:
    def test_catalogue_is_not_empty(self):
        assert len(CATALOGUE.companies) >= 10, (
            "The pitch is that we cover the companies that actually visit campuses. "
            "A handful is not a catalogue."
        )

    def test_slugs_are_unique(self):
        slugs = [c.slug for c in CATALOGUE.companies]
        assert len(slugs) == len(set(slugs)), f"duplicate slug in catalogue: {slugs}"

    @pytest.mark.parametrize("company", CATALOGUE.companies, ids=lambda c: c.slug)
    def test_topic_weights_sum_to_100(self, company: Company):
        """
        The whole roadmap is derived from these weights. A set summing to 90 does
        not fail — it silently under-allocates every topic by a tenth.
        """
        total = sum(t.weight for t in company.topics)
        assert abs(total - 100) < 0.51, f"{company.slug} weights sum to {total}"

    @pytest.mark.parametrize("company", CATALOGUE.companies, ids=lambda c: c.slug)
    def test_company_is_actually_usable(self, company: Company):
        assert company.topics, f"{company.slug} has no topics — its roadmap would be empty"
        assert company.rounds, f"{company.slug} has no rounds listed"
        assert company.programs, f"{company.slug} has no programs listed"
        assert company.drive_window, f"{company.slug} has no drive window"
        assert company.eligibility, f"{company.slug} has no eligibility line"

    @pytest.mark.parametrize("company", CATALOGUE.companies, ids=lambda c: c.slug)
    def test_accent_is_a_hex_colour(self, company: Company):
        # The UI interpolates this straight into CSS (`${accent}44`), so a malformed
        # value silently produces an invisible border rather than an error.
        assert company.accent.startswith("#") and len(company.accent) == 7, company.accent

    def test_tiers_are_known(self):
        known = {"mass_recruiter", "consulting", "product"}
        unknown = {c.tier for c in CATALOGUE.companies} - known
        assert not unknown, f"unknown tier {unknown} — the UI groups by tier and would drop these"

    def test_catalogue_has_been_verified_recently(self):
        """
        Eligibility and drive windows change every cycle. This does not fail on a
        stale file — it would break CI on a date rather than a code change — but it
        does assert someone recorded a date at all.
        """
        assert isinstance(CATALOGUE.verified, dt.date)


class TestRoadmap:
    COMPANY = get_company("tcs")

    def test_hours_track_the_budget(self):
        r = build_roadmap(self.COMPANY, weeks=8, hours_per_week=10)
        # Rounding per topic means the total drifts slightly from weeks*hours;
        # it must stay close, not match exactly.
        assert 70 <= r.total_hours <= 90

    def test_every_topic_survives_into_the_plan(self):
        r = build_roadmap(self.COMPANY, weeks=4, hours_per_week=5)
        planned = {t.name for p in r.phases for t in p.topics}
        assert planned == {t.name for t in self.COMPANY.topics}

    def test_no_topic_is_rounded_out_of_existence(self):
        """
        A short plan divides few hours across many topics. A 5%-weighted topic must
        still get an hour rather than 0 — a zero would drop it off the UI entirely
        and the candidate would never know it was meant to be studied.
        """
        r = build_roadmap(self.COMPANY, weeks=2, hours_per_week=3)
        assert all(t.hours >= 1 for p in r.phases for t in p.topics)

    def test_heaviest_topics_come_first(self):
        r = build_roadmap(self.COMPANY, weeks=8, hours_per_week=10)
        weights = [t.weight for p in sorted(r.phases, key=lambda p: p.phase) for t in p.topics]
        assert weights == sorted(weights, reverse=True), (
            "High-leverage topics must be scheduled while motivation is highest "
            "and there is still time to revisit them"
        )

    def test_plan_ends_on_the_target_date(self):
        start = dt.date(2026, 8, 1)
        r = build_roadmap(self.COMPANY, weeks=6, hours_per_week=8, start=start)
        assert r.target_date == start + dt.timedelta(weeks=6)
        # The final phase must run to the end — an earlier version left a gap
        # between the last phase and the drive.
        assert r.phases[-1].ends_on == r.target_date - dt.timedelta(days=1)

    def test_phases_are_contiguous(self):
        r = build_roadmap(self.COMPANY, weeks=9, hours_per_week=6, start=dt.date(2026, 8, 1))
        for earlier, later in zip(r.phases, r.phases[1:], strict=False):
            assert later.starts_on == earlier.ends_on + dt.timedelta(days=1), (
                "A gap or overlap between phases means days the candidate has no plan for"
            )

    @pytest.mark.parametrize(
        ("weeks", "hours"),
        [(1, 1), (52, 60), (2, 40), (24, 3)],
    )
    def test_extremes_still_produce_a_sane_plan(self, weeks: int, hours: int):
        r = build_roadmap(self.COMPANY, weeks=weeks, hours_per_week=hours)
        assert r.phases
        assert r.total_hours > 0
        assert all(p.topics for p in r.phases)

    def test_out_of_range_input_is_clamped_not_crashed(self):
        # These come off URL query params, so anything can arrive.
        r = build_roadmap(self.COMPANY, weeks=9999, hours_per_week=9999)
        assert r.weeks <= 52
        assert r.hours_per_week <= 60

    def test_disclaimer_is_always_present(self):
        """
        Eligibility numbers here are indicative. The response must always carry the
        caveat, so the UI cannot render them as official criteria by omission.
        """
        r = build_roadmap(self.COMPANY, weeks=8, hours_per_week=10)
        assert "official notification" in r.disclaimer.lower()

    def test_unknown_company_returns_none(self):
        assert get_company("not-a-real-company") is None
