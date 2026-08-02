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

    @pytest.mark.parametrize(
        ("weeks", "hours"),
        [(1, 1), (1, 3), (2, 3), (2, 5), (4, 5), (8, 10), (24, 40)],
    )
    def test_plan_never_claims_more_hours_than_the_budget(self, weeks: int, hours: int):
        """
        The bug this guards: every topic used to get max(1, ...) hours, so a
        1-week / 1-hour budget produced a SEVEN hour plan. The page told someone
        with one hour that they had a full study plan.

        A plan may cover fewer topics than exist. It may never invent time.
        """
        r = build_roadmap(self.COMPANY, weeks=weeks, hours_per_week=hours)
        budget = weeks * hours
        assert r.total_hours <= budget, (
            f"plan claims {r.total_hours}h against a {budget}h budget"
        )
        assert sum(t.hours for p in r.phases for t in p.topics) == r.total_hours

    def test_topics_that_do_not_fit_are_reported_not_hidden(self):
        r = build_roadmap(self.COMPANY, weeks=1, hours_per_week=1)
        planned = {t.name for p in r.phases for t in p.topics}
        assert r.omitted_topics, "a 1-hour budget cannot cover 7 topics — say so"
        assert not (planned & set(r.omitted_topics)), "a topic is both planned and omitted"
        assert planned | set(r.omitted_topics) == {t.name for t in self.COMPANY.topics}, (
            "every topic must be either planned or explicitly omitted — never silently dropped"
        )
        assert r.feasibility_warning and "covers" in r.feasibility_warning

    def test_a_sufficient_budget_omits_nothing(self):
        r = build_roadmap(self.COMPANY, weeks=8, hours_per_week=10)
        assert r.omitted_topics == []
        assert r.feasibility_warning is None, (
            "warning on a complete plan would train users to ignore it"
        )

    def test_omitted_topics_are_the_least_weighted_ones(self):
        r = build_roadmap(self.COMPANY, weeks=1, hours_per_week=3)
        by_name = {t.name: t.weight for t in self.COMPANY.topics}
        planned = [t.weight for p in r.phases for t in p.topics]
        dropped = [by_name[n] for n in r.omitted_topics]
        if planned and dropped:
            assert min(planned) >= max(dropped), (
                "we must drop what costs the fewest marks, not the first thing in the list"
            )

    def test_disclaimer_is_always_present(self):
        """
        Eligibility numbers here are indicative. The response must always carry the
        caveat, so the UI cannot render them as official criteria by omission.
        """
        r = build_roadmap(self.COMPANY, weeks=8, hours_per_week=10)
        assert "official notification" in r.disclaimer.lower()

    def test_unknown_company_returns_none(self):
        assert get_company("not-a-real-company") is None


class TestBusinessContext:
    """
    Guards the company-specific framing of interview questions.

    If the lookup misses, the interview silently degrades to a generic one with the
    company's name pasted in — which is exactly the thing this feature exists to
    prevent, and it fails invisibly.
    """

    @pytest.mark.parametrize("company", CATALOGUE.companies, ids=lambda c: c.slug)
    def test_every_company_has_context(self, company: Company):
        assert company.business_context, (
            f"{company.slug} has no business context — its interviews would be generic"
        )
        assert len(company.business_context) > 80, "too thin to shape a question"

    @pytest.mark.parametrize(
        "typed",
        [
            "Cognizant",
            "cognizant",
            "TCS",
            "Tech Mahindra",
            "tech mahindra",
            "LTIMindtree",
            "LTI Mindtree",
            "HCLTech",
            "HCL Tech",
            "Wipro Limited",
            "Cognizant Technology Solutions",
            "Amazon",
        ],
    )
    def test_free_text_company_names_resolve(self, typed: str):
        """
        Candidates type the company name by hand. "Tech Mahindra" slugifies to
        "tech-mahindra" while the catalogue slug is "techmahindra" — that mismatch
        made every multi-word company fall through to the generic line.
        """
        from app.services.interview.orchestrator import _business_context

        assert not _business_context(typed).startswith("(no specific"), (
            f'"{typed}" did not resolve to a catalogue company'
        )

    def test_unknown_company_degrades_gracefully(self):
        from app.services.interview.orchestrator import _business_context

        # Must not raise, and must not claim knowledge it does not have.
        assert _business_context("Some Startup Nobody Has Heard Of").startswith("(no specific")


# ─── Study-resource integrity ─────────────────────────────────────────────────


class TestStudyResourcesAreReachableAndHonest:
    """
    The failure these exist for was found by a user, not by a test: the topic
    "Percentages" linked to a Java DSA playlist. Six verified playlists had been
    spread across ten topics, and verifying that a URL *resolves* is not the same
    as verifying it is about the right subject.

    Two guards, because that bug had two halves — a link used where it did not
    belong, and a link relabelled to look like it did.
    """

    #: URLs that legitimately cover more than one topic. A full Java course does
    #: teach fundamentals, OOP and hashing, so this is real rather than an
    #: oversight — but it is written down, so adding a second cross-topic link is
    #: a deliberate act and not a silent one. That silence is how a DSA playlist
    #: ended up filed under Percentages.
    BROAD_COURSES = {
        "https://www.youtube.com/playlist?list=PL9gnSGHSqcnr_DxHsP7AW9ftq0AtAyYqJ",
    }

    #: Subtopic keys with no company topic pointing at them. Content that exists
    #: and never renders. Listed rather than asserted away so it stays visible.
    #:
    #: system_design: three reading-only subtopics. No company in the catalogue
    #: currently weights system design, which is correct for mass campus hiring —
    #: freshers are not asked to design Twitter. Whether the product companies
    #: should carry a low-level-design topic is a content decision, not a code
    #: one, so the rows stay and this records why they are dark.
    KNOWN_UNREACHABLE = {"system_design"}

    def _links(self):
        """(topic_key, subtopic_id, kind, link) for every resource in the library."""
        from app.services.prep.catalogue import load_subtopics

        for tkey, items in load_subtopics().subtopics.items():
            for s in items:
                for kind in ("video", "doc", "practice"):
                    link = getattr(s, kind)
                    if link:
                        yield tkey, s.id, kind, link

    def test_every_subtopic_key_is_reachable_from_some_company(self):
        """
        A subtopic library entry that no company topic maps to is content the
        product paid to research and no candidate will ever see.
        """
        from app.services.prep.catalogue import (
            _alias_index,
            _normalise,
            load_catalogue,
            load_subtopics,
        )

        idx = _alias_index()
        reachable = {
            idx.get(_normalise(t.name))
            for c in load_catalogue().companies
            for t in c.topics
        }
        orphans = set(load_subtopics().subtopics) - reachable - self.KNOWN_UNREACHABLE
        assert not orphans, (
            f"subtopic keys no company topic maps to: {sorted(orphans)}. Either a "
            "company needs this topic or the rows should go — dark content is worse "
            "than no content, because it looks maintained."
        )

    def test_no_company_topic_falls_through_to_nothing(self):
        """
        The mirror image: a company topic whose name matches no subtopic key
        renders as a weighted, prominent, completely empty roadmap section.
        """
        from app.services.prep.catalogue import load_catalogue, subtopics_for

        missing = [
            f"{c.slug}: {t.name!r} ({t.weight}%)"
            for c in load_catalogue().companies
            for t in c.topics
            if not subtopics_for(t.name)
        ]
        assert not missing, "company topics with no subtopics behind them: " + "; ".join(missing)

    def test_a_link_is_not_reused_across_unrelated_topics(self):
        """
        THE "Percentages → DSA playlist" GUARD. One URL appearing under two
        different topic keys means either it is a broad course — declare it — or
        it is filed somewhere it does not belong.
        """
        from collections import defaultdict

        by_url: dict[str, set[str]] = defaultdict(set)
        for tkey, _sid, _kind, link in self._links():
            by_url[link.url].add(tkey)

        offenders = {
            url: sorted(keys)
            for url, keys in by_url.items()
            if len(keys) > 1 and url not in self.BROAD_COURSES
        }
        assert not offenders, (
            "these links are used under more than one topic without being declared "
            f"broad courses: {offenders}"
        )

    def test_the_same_url_always_carries_the_same_title(self):
        """
        The other half of that bug: the URL was fine, the label was not. One URL
        presented under two titles means at least one of them is a lie about what
        the candidate is about to open.
        """
        from collections import defaultdict

        titles: dict[str, set[str]] = defaultdict(set)
        for _tkey, _sid, _kind, link in self._links():
            titles[link.url].add(link.title)

        inconsistent = {u: sorted(t) for u, t in titles.items() if len(t) > 1}
        assert not inconsistent, (
            f"the same URL is presented under different titles: {inconsistent}"
        )

    @pytest.mark.parametrize("kind", ["video", "doc", "practice"])
    def test_links_are_absolute_https(self, kind: str):
        bad = [
            f"{tkey}/{sid} {link.url}"
            for tkey, sid, k, link in self._links()
            if k == kind and not link.url.startswith("https://")
        ]
        assert not bad, f"non-https or relative {kind} links: {bad}"

    def test_no_subtopic_is_a_dead_row(self):
        """A subtopic with nothing to read, watch or practise is a checkbox."""
        from app.services.prep.catalogue import load_subtopics

        dead = [
            f"{tkey}/{s.id}"
            for tkey, items in load_subtopics().subtopics.items()
            for s in items
            if not (s.doc or s.video or s.practice)
        ]
        assert not dead, f"subtopics with no resources at all: {dead}"
