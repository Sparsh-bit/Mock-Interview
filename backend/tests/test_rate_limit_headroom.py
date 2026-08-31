"""
The headroom analysis must keep describing this codebase — tests/test_rate_limit_headroom.py

scripts/rate_limit_headroom.py estimates peak RPM/ITPM/OTPM at 200 concurrent users, and its
whole claim to be worth reading is that its inputs come from the code rather than from
somebody's memory of the code. That claim decays silently: raise REPORT_CONCURRENCY or
INTERVIEW_QUESTION_COUNT and the analysis keeps printing confident numbers about a system
that no longer exists.

So these tests pin the [CODE] constants to their sources. They are not testing arithmetic —
they are testing that the arithmetic is still about the right system.

The [ASSUMED] constants are deliberately NOT pinned. They are judgements about human
behaviour, they are meant to be argued with, and a test would only make them look settled.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.api.v1.reports import report_token_budget
from app.core.config import settings
from app.services.report.composer import BATCH_SIZE, plan_batches


def _load_script():
    """
    Import the script by path — it lives in scripts/, which is not a package.

    REGISTERED IN sys.modules BEFORE exec_module, and that is required rather than tidy:
    the script defines a dataclass whose __add__ is annotated `-> "Load"`, and dataclasses
    resolves a string annotation by looking the defining module up in sys.modules. Without
    the registration that lookup returns None and the import dies inside dataclasses.
    """
    path = Path(__file__).resolve().parents[1] / "scripts" / "rate_limit_headroom.py"
    spec = importlib.util.spec_from_file_location("rate_limit_headroom", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def analysis():
    return _load_script()


class TestItStillDescribesThisCodebase:
    def test_the_interview_shape_matches_settings(self, analysis):
        assert analysis.INTERVIEW_QUESTION_COUNT == settings.INTERVIEW_QUESTION_COUNT
        assert analysis.INTERVIEW_MAX_CROSS_QUESTIONS == settings.INTERVIEW_MAX_CROSS_QUESTIONS

    def test_the_report_concurrency_matches_settings(self, analysis):
        """
        The one that matters most. REPORT_CONCURRENCY x replicas is what bounds the report
        burst, so it is the analysis's binding constraint — raising it without re-running
        this is how a rate limit gets discovered in production.
        """
        assert analysis.REPORT_CONCURRENCY == settings.REPORT_CONCURRENCY

    def test_the_report_batch_size_matches_the_composer(self, analysis):
        assert analysis.REPORT_BATCH_SIZE == BATCH_SIZE

    def test_the_call_count_per_report_matches_what_the_composer_actually_plans(self, analysis):
        """
        A report is one summary call plus one per batch. The cost model prices a report as a
        single call, which is fine for dollars and wrong for RPM — this is the number that
        stops the analysis inheriting that simplification.
        """
        planned = 1 + len(plan_batches(settings.INTERVIEW_QUESTION_COUNT))
        assert planned == analysis.REPORT_CALLS

    def test_the_replica_count_matches_the_application_default(self, analysis):
        """
        PROCESS_COUNT, not WEB_REPLICA_COUNT. What multiplies a per-process semaphore is the
        number of PROCESSES — replicas times uvicorn workers — so an extra worker moves the
        report burst exactly as much as an extra replica. Pinned against the derived value so
        raising WEB_CONCURRENCY cannot leave this analysis quietly describing a smaller fleet.
        """
        assert analysis.REPLICAS == settings.PROCESS_COUNT

    def test_the_measured_report_output_fits_under_the_configured_budget(self, analysis):
        """
        If the measured output figure ever exceeds what the code will let a report generate,
        the analysis is over-estimating OTPM against a response that cannot happen.
        """
        assert report_token_budget(
            settings.INTERVIEW_QUESTION_COUNT
        ) >= analysis.REPORT_TOTAL_OUTPUT


class TestTheModelBehavesTheWayItClaimsTo:
    def test_cache_reads_are_excluded_from_the_itpm_estimate(self, analysis):
        """
        The single most consequential property of Anthropic's limits for this product:
        cache_read_input_tokens do not count toward ITPM on sonnet-5. A model that counted
        them would put the GD panel's 2,856-token rulebook into the estimate 26 times a
        round and overstate ITPM by roughly 9x for that feature.
        """
        call = analysis.Call("t", uncached_input=100, cached_input=10_000, output=50)
        load = analysis.sustained(call, calls_per_minute=10)
        assert load.itpm == 1_000, "cached input leaked into the ITPM estimate"

    def test_the_cache_write_is_charged_once_per_round_not_never(self, analysis):
        """
        The first turn of a GD round WRITES the rulebook to cache, and a write does count.
        Excluding it entirely would be the mirror-image error of counting every read.
        """
        call = analysis.Call("t", uncached_input=0, cached_input=2_600, output=50)
        load = analysis.sustained(call, calls_per_minute=analysis.GD_PANEL_TURNS,
                                  first_call_writes_cache=True)
        assert load.itpm == pytest.approx(2_600), "the cache write was not charged once"

    def test_output_tokens_are_the_binding_constraint_at_the_current_replica_count(self, analysis):
        """
        The analysis's headline finding, pinned so a future edit cannot quietly invert it
        without someone noticing. OTPM is one fifth of ITPM on every published tier, and
        this product's expensive call is one that writes a lot.
        """
        peak, _ = analysis.correlated_report_peak()
        rpm_limit, itpm_limit, otpm_limit = analysis.TIERS["Start"]
        assert peak.otpm / otpm_limit > peak.rpm / rpm_limit
        assert peak.otpm / otpm_limit > peak.itpm / itpm_limit

    def test_the_script_runs(self, analysis, capsys):
        """It is a deliverable somebody has to be able to run, not just import."""
        analysis.main()
        out = capsys.readouterr().out
        assert "BINDING CONSTRAINT" in out
        assert "peak OTPM" in out
