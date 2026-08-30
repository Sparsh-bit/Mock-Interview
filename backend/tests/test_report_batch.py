"""
A report can never be permanently stuck — tests/test_report_batch.py

Reports now have a second, cheaper way of being produced: submitted to Anthropic's Message
Batches API and answered on the provider's schedule at HALF PRICE. docs/AI-COST-MODEL.md
names it the single largest saving left in the product — about −$0.062 a report, roughly 40%
of a warm interview, and more than every prompt-caching win put together.

WHAT MAKES IT DANGEROUS IS EXACTLY WHAT MAKES IT CHEAP. The work leaves the request. It comes
back in minutes, or in twenty-four hours, or — if the provider errors it, expires it, or the
batch id is simply wrong — never. Every one of those is a way for a candidate to be left
looking at "your report is being prepared" for the rest of time, having finished an interview
they paid for.

So these tests are not really about batching. They are about the invariant:

    EVERY ROUTE OUT OF THE CHEAP PATH ENDS SOMEWHERE A REPORT GETS WRITTEN.

Four independent guarantees, each tested here on its own, because a guarantee that depends on
another guarantee is one guarantee:

  1. Submission fails            -> the synchronous path runs in the same request.
  2. One batch attempt, ever     -> a session that has tried never tries again.
  3. A batch that never ends     -> abandoned at the deadline.
  4. A batch we cannot even see  -> abandoned after a few failed lookups.

And the two quieter ways this could go wrong, which no amount of state-machine correctness
would catch:

  * BATCHING SOMETHING SOMEBODY IS WAITING FOR. The allowlist is closed and every
    interview, panel, GD, quiz and code call site is outside it. A batched interview
    question would not be a cost saving, it would be a candidate staring at a spinner for
    an hour.

  * ATTACHING ONE CANDIDATE'S FEEDBACK TO THE WRONG QUESTIONS. Batch results come back in
    COMPLETION order, so the custom_id is the only link between a response and the work it
    did. It is derived from the question ids, not from the batch's position, and the test
    below is what says that matters.

No network calls anywhere in this file. The provider is a fake and every id is invented.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from app.services.ai.base_provider import ProviderError, ProviderMessage
from app.services.report.batch_job import (
    DEFAULT_MAX_LOOKUP_FAILURES,
    DEFAULT_MAX_WAIT_SECONDS,
    SUMMARY_PART,
    Collection,
    Decision,
    JobStatus,
    JobView,
    decide,
    may_batch,
    part_id,
    status_after_collection,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]

_T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


def _live(**kw) -> JobView:
    """A job that was submitted at _T0 and is still processing."""
    return JobView(status=JobStatus.PROCESSING, submitted_at=_T0, **kw)


# ─────────────────────────────────────────────────────────────────────────────
# The state machine
# ─────────────────────────────────────────────────────────────────────────────


class TestTheHappyPath:
    def test_a_running_batch_inside_its_deadline_is_waited_for(self):
        assert (
            decide(_live(), processing_status="in_progress", now=_T0 + timedelta(seconds=30))
            is Decision.WAIT
        )

    def test_an_ended_batch_is_collected(self):
        assert (
            decide(_live(), processing_status="ended", now=_T0 + timedelta(seconds=30))
            is Decision.COLLECT
        )

    def test_an_ended_batch_is_collected_even_past_the_deadline(self):
        """
        The deadline decides how long we WAIT, never whether we take what has arrived.

        Results that exist are already paid for. Throwing them away to honour a deadline
        would be spending money in order to be punctual — and it would send the session
        back through the synchronous path to buy the same answers a second time.
        """
        very_late = _T0 + timedelta(seconds=DEFAULT_MAX_WAIT_SECONDS * 10)
        assert decide(_live(), processing_status="ended", now=very_late) is Decision.COLLECT


class TestABatchThatNeverEnds:
    def test_it_is_abandoned_at_the_deadline(self):
        # Guarantee 3. A provider that accepts a batch and goes quiet costs one wait, once.
        at_deadline = _T0 + timedelta(seconds=DEFAULT_MAX_WAIT_SECONDS)
        assert (
            decide(_live(), processing_status="in_progress", now=at_deadline)
            is Decision.FALL_BACK
        )

    def test_one_second_before_the_deadline_it_is_still_waited_for(self):
        # The boundary in the other direction, so "expired" cannot quietly become
        # "expired-ish" and start abandoning healthy batches — which would cost the entire
        # saving on every report while looking like nothing at all.
        nearly = _T0 + timedelta(seconds=DEFAULT_MAX_WAIT_SECONDS - 1)
        assert decide(_live(), processing_status="in_progress", now=nearly) is Decision.WAIT

    def test_a_cancelled_batch_is_not_waited_out(self):
        # "canceling" ends with no usable results. Waiting for that to be confirmed only
        # delays the report by the whole deadline for an answer already known.
        assert (
            decide(_live(), processing_status="canceling", now=_T0 + timedelta(seconds=5))
            is Decision.FALL_BACK
        )

    def test_an_unrecognised_status_is_treated_as_unfinished_not_as_broken(self):
        # A status this SDK version does not know about is not evidence of anything wrong,
        # and abandoning on it would break the feature the day the provider adds a state.
        # The deadline still bounds it.
        assert (
            decide(_live(), processing_status="quantum_superposition", now=_T0)
            is Decision.WAIT
        )
        past = _T0 + timedelta(seconds=DEFAULT_MAX_WAIT_SECONDS + 1)
        assert (
            decide(_live(), processing_status="quantum_superposition", now=past)
            is Decision.FALL_BACK
        )


class TestABatchWeCannotSee:
    """
    `processing_status=None` means the provider could not be reached AT ALL.

    Distinct from "not finished", and it is the case that would otherwise leave a job in
    `processing` forever: a deleted batch, a rotated key, an id from another account. None
    of those ever becomes "ended", so nothing would ever collect it and nothing would ever
    give up on it.
    """

    def test_the_first_failed_lookup_is_forgiven(self):
        # A blip is fixed by the next poll. Abandoning on one would throw away the whole
        # saving over a dropped connection.
        assert decide(_live(lookup_failures=0), processing_status=None, now=_T0) is Decision.WAIT

    def test_it_is_abandoned_once_the_failures_stop_looking_like_a_blip(self):
        # Guarantee 4. The count is of CONSECUTIVE failures — batch_runner clears it on any
        # successful poll — so three here means three in a row, which is a batch that is
        # not there rather than a network having a moment.
        job = _live(lookup_failures=DEFAULT_MAX_LOOKUP_FAILURES - 1)
        assert decide(job, processing_status=None, now=_T0) is Decision.FALL_BACK

    def test_an_unreachable_batch_is_abandoned_even_well_inside_its_deadline(self):
        # The two rules are independent. A batch submitted a second ago that cannot be
        # found is not going to be found in fourteen minutes either.
        job = _live(lookup_failures=DEFAULT_MAX_LOOKUP_FAILURES - 1)
        assert decide(job, processing_status=None, now=_T0 + timedelta(seconds=1)) is (
            Decision.FALL_BACK
        )


class TestTerminalJobsStayTerminal:
    def test_a_completed_job_is_done_not_waiting(self):
        # DONE, and specifically not WAIT. A completed job answering WAIT would have the
        # client polling a report it already has, forever.
        job = JobView(status=JobStatus.COMPLETED, submitted_at=_T0)
        assert decide(job, processing_status="ended", now=_T0) is Decision.DONE

    @pytest.mark.parametrize("status", [JobStatus.FAILED, JobStatus.ABANDONED])
    def test_a_dead_job_sends_the_session_synchronous(self, status):
        job = JobView(status=status, submitted_at=_T0)
        assert decide(job, processing_status="in_progress", now=_T0) is Decision.FALL_BACK

    def test_a_dead_job_is_not_resurrected_by_the_batch_finishing_later(self):
        # The batch may well end after we stopped being its audience. That must not undo
        # the decision — by then the report has been generated synchronously, and
        # collecting would overwrite a real report with a stale one.
        job = JobView(status=JobStatus.ABANDONED, submitted_at=_T0)
        assert decide(job, processing_status="ended", now=_T0) is Decision.FALL_BACK


class TestOneAttemptEver:
    """
    Guarantee 2, and the one that makes a loop structurally impossible rather than merely
    unlikely. There is no counter to get wrong and no cooldown to mistune: a session that
    has a job row does not get another batch, whatever state that row is in.
    """

    def test_a_session_that_has_never_tried_may_batch(self):
        assert may_batch(None) is True

    @pytest.mark.parametrize(
        "status",
        [JobStatus.PROCESSING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.ABANDONED],
    )
    def test_a_session_that_has_tried_never_tries_again(self, status):
        assert may_batch(JobView(status=status, submitted_at=_T0)) is False


class TestPartialResultsAreAReport:
    def test_some_parts_landing_is_completed(self):
        # The same judgement the synchronous path already makes on a failed analysis batch.
        # Calling this "failed" would throw away grading that was done and paid for, and
        # send the session back to full price to buy it again.
        c = Collection(succeeded={"analysis:a": "{}"}, failed={"analysis:b": "errored"})
        assert status_after_collection(c) is JobStatus.COMPLETED

    def test_nothing_landing_is_failed(self):
        c = Collection(succeeded={}, failed={SUMMARY_PART: "expired"})
        assert status_after_collection(c) is JobStatus.FAILED

    def test_an_entirely_empty_collection_is_failed_not_completed(self):
        # A batch that ended with no entries at all. There is genuinely nothing to build
        # on, and calling it complete would store an empty report as the final answer.
        assert status_after_collection(Collection({}, {})) is JobStatus.FAILED


class TestTheClockCannotProduceNonsense:
    def test_a_job_submitted_in_the_future_is_zero_seconds_old(self):
        # `submitted_at` comes from the database and `now` from this process; they are not
        # the same clock. A negative age is harmless arithmetically and reads as nonsense
        # in the logs at exactly the moment somebody is asking why reports are slow.
        assert _live().age_seconds(_T0 - timedelta(seconds=30)) == 0.0

    def test_a_clock_skewed_job_is_not_instantly_expired(self):
        assert _live().expired(_T0 - timedelta(seconds=30)) is False


# ─────────────────────────────────────────────────────────────────────────────
# Matching a result back to the work it did
# ─────────────────────────────────────────────────────────────────────────────


class TestTheCustomIdIsDerivedFromTheQuestions:
    """
    `analysis:0`, `analysis:1` would have been simpler and would have been a real bug.

    Batches are planned over the questions still UNGRADED. If anything grades a question
    between submission and collection — a synchronous fallback, a completion pass — batch 1
    no longer covers the questions it covered when it was submitted. A positional id would
    then attach one set of answers' feedback to a different set of questions, silently, and
    the candidate would read a stranger's analysis under their own question.
    """

    def test_the_same_questions_in_the_same_order_get_the_same_id(self):
        assert part_id(["q1", "q2", "q3"]) == part_id(["q1", "q2", "q3"])

    def test_different_questions_get_a_different_id(self):
        assert part_id(["q1", "q2", "q3"]) != part_id(["q1", "q2", "q4"])

    def test_the_order_is_part_of_the_identity(self):
        # The prompt asks for entries "in this order", so a reordered slice is a different
        # request and must not be served a previous slice's answer.
        assert part_id(["q1", "q2"]) != part_id(["q2", "q1"])

    def test_a_slice_that_shrank_does_not_match_the_old_one(self):
        # THE CASE THE POSITIONAL ID GOT WRONG. Six questions were submitted; one has since
        # been graded elsewhere; the remaining five are now a different slice. The id must
        # miss, so that part is generated live rather than filled with the six-question
        # answer.
        six = [f"q{i}" for i in range(6)]
        assert part_id(six[:5]) != part_id(six)

    def test_the_summary_part_has_a_fixed_id_of_its_own(self):
        # There is exactly one, it covers no questions, and it must not collide with any
        # analysis id however the interview is sliced.
        assert SUMMARY_PART == "summary"
        assert part_id([]) != SUMMARY_PART


# ─────────────────────────────────────────────────────────────────────────────
# Nothing anybody is waiting for may be batched
# ─────────────────────────────────────────────────────────────────────────────


class TestOnlyTheReportMayBeBatched:
    """
    The failure this guards is not a bug in the batch code. It is somebody later reaching
    for the cheap path at a call site where a candidate is waiting — and the symptom would
    be a spinner lasting anywhere up to twenty-four hours, with nothing in the logs saying
    why. Nothing else in the system would stop it.
    """

    def test_the_allowlist_is_exactly_the_two_halves_of_a_report(self):
        from app.services.ai.batch import BATCHABLE_FEATURES

        assert set(BATCHABLE_FEATURES) == {"report_generation", "report_analysis"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "feature",
        [
            "interview_question",
            "interview_plan",
            "gd_panel",
            "panel_dialogue",
            "quiz_generation",
            "code_evaluation",
            "answer_evaluation",
            "communication_evaluation",
            "resume_analysis",
        ],
    )
    async def test_a_feature_somebody_is_waiting_for_is_refused(self, feature):
        from app.services.ai import batch as ai_batch

        part = ai_batch.BatchPart(
            custom_id="x",
            feature=feature,
            messages=[ProviderMessage(role="user", content="hi")],
            max_tokens=100,
        )
        with pytest.raises(ProviderError, match="not batchable"):
            await ai_batch.submit([part])

    @pytest.mark.asyncio
    async def test_one_forbidden_part_refuses_the_whole_batch(self):
        # Not "drop the bad one and submit the rest". A mixed batch means a call site is
        # wired wrong, and quietly submitting the acceptable half would hide it.
        from app.services.ai import batch as ai_batch

        parts = [
            ai_batch.BatchPart(
                custom_id="ok",
                feature="report_analysis",
                messages=[ProviderMessage(role="user", content="hi")],
                max_tokens=100,
            ),
            ai_batch.BatchPart(
                custom_id="bad",
                feature="interview_question",
                messages=[ProviderMessage(role="user", content="hi")],
                max_tokens=100,
            ),
        ]
        with pytest.raises(ProviderError, match="not batchable"):
            await ai_batch.submit(parts)

    def test_no_live_call_site_reaches_the_batch_module(self):
        """
        Source-level, because the allowlist can only fire once the mistake has shipped.

        Only api/v1/reports.py and the report services may import services.ai.batch. An
        import anywhere else is a call site being pointed at a path that answers in hours.
        """
        allowed = {
            "app/api/v1/reports.py",
            "app/services/ai/batch.py",
            "app/services/report/batch_runner.py",
        }
        offenders = []
        for path in (BACKEND / "app").rglob("*.py"):
            rel = str(path.relative_to(BACKEND))
            if rel in allowed:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                # Import/ImportFrom ONLY. `ast.Global` and `ast.Nonlocal` also carry a
                # `names` attribute, but of plain strings — walking every node and reading
                # `.name` off them is an AttributeError, which is how this test first failed.
                if not isinstance(node, ast.Import | ast.ImportFrom):
                    continue
                mod = getattr(node, "module", None) or ""
                names = [a.name for a in node.names]
                if "services.ai.batch" in mod or any("services.ai.batch" in n for n in names):
                    offenders.append(rel)
                if mod.endswith("services.ai") and "batch" in names:
                    offenders.append(rel)
        assert not offenders, (
            f"{sorted(set(offenders))} import the batch module. The Batches API answers on "
            "the provider's schedule (minutes, up to 24h) — only the report may use it."
        )


# ─────────────────────────────────────────────────────────────────────────────
# The batch and the live path must be the SAME request
# ─────────────────────────────────────────────────────────────────────────────


class TestABatchedReportIsTheSameReport:
    def test_both_paths_build_the_analysis_turn_from_one_function(self):
        """
        A batched request and a live one must be byte-identical apart from how they are
        submitted. If they diverge, a report generated cheaply is a different report from
        one generated live — and no test that exercises only one of them would ever say so.

        Asserted on the source because the divergence would be silent: two f-strings that
        drifted apart still produce valid reports, just not the same one. It also matters
        for money — the system block is provider-cached on its exact bytes, so a second
        wording would halve the cache hit rate rather than fail.
        """
        src = (BACKEND / "app" / "api" / "v1" / "reports.py").read_text()
        assert src.count("def analysis_user_content(") == 1
        assert src.count("analysis_user_content(slice_lines)") == 2, (
            "the synchronous path and the batch submission must both build the analysis "
            "user turn from analysis_user_content — if one inlines its own f-string, the "
            "two paths are asking different questions"
        )

    def test_the_batch_path_reuses_the_provider_payload_builder(self):
        # Same argument one layer down: model, output clamp, thinking/effort mapping and
        # the system/messages split all come from _build_payload, so a batched call cannot
        # quietly buy reasoning the live one does not.
        src = (BACKEND / "app" / "services" / "ai" / "anthropic_provider.py").read_text()
        assert src.count("def _build_payload(") == 1
        assert src.count("self._build_payload(request)") == 2

    def test_the_batch_parts_carry_the_report_cost_tier_not_a_cheaper_one(self):
        # A batch is already half price. Dropping the tier as well would be paying less for
        # a worse report and calling it one saving.
        src = (BACKEND / "app" / "api" / "v1" / "reports.py").read_text()
        submit = src.split("async def _submit_report_batch(")[1].split("\ndef ")[0]
        assert "CostTier.BALANCED" in submit
        assert "CostTier.CHEAP" not in submit

    def test_the_batch_parts_keep_prompt_caching_on(self):
        # The two savings compose: a cached read inside a batched request bills at 0.5x the
        # already-reduced cache rate. Losing the marker here would give back a win that is
        # already banked.
        src = (BACKEND / "app" / "api" / "v1" / "reports.py").read_text()
        submit = src.split("async def _submit_report_batch(")[1].split("\ndef ")[0]
        assert submit.count("cache_system=True") == 2


class TestTheDiscountIsRealAndRecorded:
    def test_a_batched_call_costs_half(self):
        """
        The 50% is the entire reason this exists, so it is measured rather than trusted.

        Both figures come from the same _to_response, on the same fake usage, differing
        only in the multiplier — which is what makes this a test of the discount and not of
        the price sheet.
        """
        from app.services.ai.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5")
        message = _FakeMessage(input_tokens=10_000, output_tokens=5_000)
        log = _NullLog()

        full = provider._to_response(message, "claude-sonnet-5", log)
        batched = provider._to_response(
            message, "claude-sonnet-5", log, price_multiplier=0.5
        )

        assert full.estimated_cost_usd is not None
        assert batched.estimated_cost_usd == pytest.approx(full.estimated_cost_usd / 2, rel=1e-6)
        # Tokens are unchanged — the discount is on the price, not on the usage, and a
        # ledger that halved the token counts would misreport how much work was done.
        assert batched.prompt_tokens == full.prompt_tokens
        assert batched.completion_tokens == full.completion_tokens

    def test_the_ledger_would_not_show_reports_becoming_free(self):
        # Every synchronous call records itself inside generate_structured. A batched one
        # has no such moment — the request and the response are hours apart, and the
        # response arrives in somebody else's HTTP call. Without an explicit write the most
        # expensive feature in the product would vanish from the ledger AI-COST-MODEL.md is
        # supposed to be re-derived from.
        src = (BACKEND / "app" / "services" / "report" / "batch_runner.py").read_text()
        assert "record_call(" in src
        assert '"report_generation"' in src
        assert '"report_analysis"' in src


class TestTheDefaultIsOff:
    def test_batching_is_not_on_by_default(self):
        """
        Turning this on changes what a candidate sees after an interview from "here is your
        report" to "we are preparing your report". AI-COST-MODEL.md is explicit that this is
        a product decision, not a refactor — worth costing before the price is set, because
        it changes what the free tier can afford. So the path is complete and one env var
        from live, and flipping it is somebody's decision rather than a default.
        """
        from app.core.config import Settings

        assert Settings.model_fields["REPORT_BATCH_ENABLED"].default is False

    def test_the_wait_is_bounded_and_the_bound_is_configurable(self):
        from app.core.config import Settings

        default = Settings.model_fields["REPORT_BATCH_MAX_WAIT_SECONDS"].default
        assert default == DEFAULT_MAX_WAIT_SECONDS
        # Never unbounded. An unbounded patience setting is the stuck report this whole
        # file exists to rule out, reintroduced as configuration.
        assert 60 <= default <= 24 * 3600


# ─────────────────────────────────────────────────────────────────────────────
# Fallbacks, end to end through batch_runner
# ─────────────────────────────────────────────────────────────────────────────


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0


class _FakeMessage:
    def __init__(self, input_tokens=1000, output_tokens=500, text='{"ok": true}'):
        from anthropic.types import TextBlock

        self.usage = _FakeUsage(input_tokens, output_tokens)
        self.content = [TextBlock(type="text", text=text, citations=None)]
        self.stop_reason = "end_turn"
        self.model = "claude-sonnet-5"


class _NullLog:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...
    def debug(self, *a, **k): ...
    def bind(self, **k):
        return self


class _FakeJob:
    """A `report_jobs` row, without a database."""

    def __init__(self, *, status="processing", age_seconds=10, lookup_failures=0, parts=None):
        self.status = status
        self.created_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
        self.lookup_failures = lookup_failures
        self.batch_id = "msgbatch_fake"
        self.provider = "anthropic"
        self.parts = parts if parts is not None else {SUMMARY_PART: {"kind": "summary"}}
        self.error = None


class _FakeDB:
    async def rollback(self): ...
    async def commit(self): ...


class TestTheRunnerNeverRaisesAtTheCaller:
    """
    batch_runner.advance is called from inside the report endpoint. Anything it raises is a
    500, and a 500 from that handler reaches the browser as an opaque CORS failure — so a
    provider having a bad minute would look to the candidate like the app being broken.
    """

    @pytest.mark.asyncio
    async def test_an_unreachable_provider_is_a_wait_not_an_exception(self, monkeypatch):
        from app.services.report import batch_runner

        async def boom(_batch_id):
            raise ProviderError("connection reset", provider="anthropic")

        monkeypatch.setattr(batch_runner.ai_batch, "poll", boom)
        job = _FakeJob(lookup_failures=0)
        result = await batch_runner.advance(_FakeDB(), job)
        assert result.status is JobStatus.PROCESSING
        # Counted, so the next failure is closer to abandoning rather than forgiven forever.
        assert job.lookup_failures == 1

    @pytest.mark.asyncio
    async def test_repeated_unreachability_abandons_the_job(self, monkeypatch):
        from app.services.report import batch_runner

        async def boom(_batch_id):
            raise ProviderError("no such batch", provider="anthropic")

        monkeypatch.setattr(batch_runner.ai_batch, "poll", boom)
        job = _FakeJob(lookup_failures=DEFAULT_MAX_LOOKUP_FAILURES - 1)
        result = await batch_runner.advance(_FakeDB(), job)
        assert result.status is JobStatus.ABANDONED
        assert job.status == "abandoned"
        assert job.error and "unreachable" in job.error

    @pytest.mark.asyncio
    async def test_a_successful_poll_clears_a_previous_failure(self, monkeypatch):
        """
        The count is of CONSECUTIVE failures. Without the reset, three blips spread over an
        hour would abandon a perfectly healthy batch — and the whole 50% saving with it.
        """
        from app.services.ai.batch import BatchStatus
        from app.services.report import batch_runner

        async def ok(_batch_id):
            return BatchStatus(processing_status="in_progress", counts={"processing": 3})

        monkeypatch.setattr(batch_runner.ai_batch, "poll", ok)
        job = _FakeJob(lookup_failures=2)
        result = await batch_runner.advance(_FakeDB(), job)
        assert result.status is JobStatus.PROCESSING
        assert job.lookup_failures == 0

    @pytest.mark.asyncio
    async def test_a_stalled_batch_is_abandoned_at_the_deadline(self, monkeypatch):
        from app.services.ai.batch import BatchStatus
        from app.services.report import batch_runner

        async def still_going(_batch_id):
            return BatchStatus(processing_status="in_progress", counts={"processing": 4})

        monkeypatch.setattr(batch_runner.ai_batch, "poll", still_going)
        job = _FakeJob(age_seconds=DEFAULT_MAX_WAIT_SECONDS + 60)
        result = await batch_runner.advance(_FakeDB(), job)
        assert result.status is JobStatus.ABANDONED
        assert job.status == "abandoned"

    @pytest.mark.asyncio
    async def test_results_that_cannot_be_read_do_not_lose_the_batch_immediately(
        self, monkeypatch
    ):
        # Reading results is a separate call from checking status and can blip on its own.
        # The results stay at the provider for 29 days, so one failure must not abandon a
        # batch that has genuinely finished.
        from app.services.ai.batch import BatchStatus
        from app.services.report import batch_runner

        async def ended(_batch_id):
            return BatchStatus(processing_status="ended", counts={"succeeded": 3})

        async def unreadable(_batch_id):
            raise ProviderError("504", provider="anthropic")

        monkeypatch.setattr(batch_runner.ai_batch, "poll", ended)
        monkeypatch.setattr(batch_runner.ai_batch, "collect", unreadable)
        job = _FakeJob(lookup_failures=0)
        result = await batch_runner.advance(_FakeDB(), job)
        assert result.status is JobStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_results_that_keep_failing_to_read_do_abandon_it(self, monkeypatch):
        from app.services.ai.batch import BatchStatus
        from app.services.report import batch_runner

        async def ended(_batch_id):
            return BatchStatus(processing_status="ended", counts={"succeeded": 3})

        async def unreadable(_batch_id):
            raise ProviderError("504", provider="anthropic")

        monkeypatch.setattr(batch_runner.ai_batch, "poll", ended)
        monkeypatch.setattr(batch_runner.ai_batch, "collect", unreadable)
        job = _FakeJob(lookup_failures=DEFAULT_MAX_LOOKUP_FAILURES - 1)
        result = await batch_runner.advance(_FakeDB(), job)
        assert result.status is JobStatus.ABANDONED


class TestCollection:
    @pytest.mark.asyncio
    async def test_a_finished_batch_is_stored_on_the_row_so_it_is_read_once(
        self, monkeypatch
    ):
        """
        The report is built from these in a LATER step. Storing them means that step cannot
        depend on the provider still being reachable by then — and that opening the report
        page ten times is ten reads of a JSONB column, not ten requests to Anthropic for
        bytes we already have.
        """
        from app.services.ai.anthropic_provider import AnthropicProvider
        from app.services.ai.batch import BatchStatus
        from app.services.report import batch_runner

        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5")
        response = provider._to_response(
            _FakeMessage(text='{"executive_summary": "ok"}'),
            "claude-sonnet-5",
            _NullLog(),
            price_multiplier=0.5,
        )

        async def ended(_batch_id):
            return BatchStatus(processing_status="ended", counts={"succeeded": 1})

        async def results(_batch_id):
            return {SUMMARY_PART: response, "analysis:dead": "errored"}

        recorded: list[str] = []

        async def fake_record(**kw):
            recorded.append(kw["feature"])

        monkeypatch.setattr(batch_runner.ai_batch, "poll", ended)
        monkeypatch.setattr(batch_runner.ai_batch, "collect", results)
        monkeypatch.setattr("app.services.ai.usage.record_call", fake_record)

        job = _FakeJob(parts={SUMMARY_PART: {"kind": "summary"}})
        advanced = await batch_runner.advance(_FakeDB(), job)

        assert advanced.status is JobStatus.COMPLETED
        assert advanced.results[SUMMARY_PART] == '{"executive_summary": "ok"}'
        assert advanced.failures == {"analysis:dead": "errored"}
        assert job.parts[SUMMARY_PART]["raw"] == '{"executive_summary": "ok"}'
        assert job.parts["analysis:dead"]["error"] == "errored"
        # Recorded against report_generation, at the batch rate — see the ledger test above.
        assert recorded == ["report_generation"]

    @pytest.mark.asyncio
    async def test_a_terminal_job_is_answered_from_the_row_without_touching_the_provider(
        self, monkeypatch
    ):
        from app.services.report import batch_runner

        async def must_not_be_called(_batch_id):
            raise AssertionError("a terminal job must not poll the provider again")

        monkeypatch.setattr(batch_runner.ai_batch, "poll", must_not_be_called)
        job = _FakeJob(
            status="completed", parts={SUMMARY_PART: {"kind": "summary", "raw": "{}"}}
        )
        advanced = await batch_runner.advance(_FakeDB(), job)
        assert advanced.status is JobStatus.COMPLETED
        assert advanced.results == {SUMMARY_PART: "{}"}

    @pytest.mark.asyncio
    async def test_a_batch_where_every_part_died_is_failed_not_completed(self, monkeypatch):
        from app.services.ai.batch import BatchStatus
        from app.services.report import batch_runner

        async def ended(_batch_id):
            return BatchStatus(processing_status="ended", counts={"errored": 2})

        async def results(_batch_id):
            return {SUMMARY_PART: "expired", "analysis:x": "errored"}

        monkeypatch.setattr(batch_runner.ai_batch, "poll", ended)
        monkeypatch.setattr(batch_runner.ai_batch, "collect", results)
        job = _FakeJob()
        advanced = await batch_runner.advance(_FakeDB(), job)
        assert advanced.status is JobStatus.FAILED
        assert not advanced.usable


# ─────────────────────────────────────────────────────────────────────────────
# The endpoint's own guarantees, read from the source
# ─────────────────────────────────────────────────────────────────────────────


class TestSubmissionFailureCostsNothingButMoney:
    """
    Guarantee 1. Everything about submitting can fail — no provider that batches, a refused
    submission, a spent daily budget, a table that has not been migrated yet — and the
    answer is always the same: generate synchronously, in this same request, and never tell
    the candidate a cheaper route was tried.
    """

    def test_the_submitter_swallows_everything_and_returns_none(self):
        src = (BACKEND / "app" / "api" / "v1" / "reports.py").read_text()
        fn = src.split("async def _submit_report_batch(")[1].split("\ndef ")[0]
        assert "except Exception as exc:" in fn
        assert "return None" in fn

    def test_the_caller_falls_through_when_submission_returns_none(self):
        src = (BACKEND / "app" / "api" / "v1" / "reports.py").read_text()
        assert "if submitted is not None:" in src, (
            "submission must be treated as optional at the call site — a None that was "
            "returned rather than checked would produce a report with no placeholder"
        )

    def test_a_missing_report_jobs_table_does_not_break_reports(self):
        # The pre-migration window: this repo's migrations are applied by hand against
        # Supabase, so there is always a period where the code is live and the table is
        # not. An UndefinedTable raised here would 500 the report endpoint for everybody.
        src = (BACKEND / "app" / "api" / "v1" / "reports.py").read_text()
        fn = src.split("async def load_batch_job(")[1].split("\ndef ")[0]
        assert "except SQLAlchemyError" in fn
        assert "await db.rollback()" in fn, (
            "a failed statement poisons the transaction in Postgres — without a rollback "
            "every later query in this request fails too, including the report write"
        )
        assert "return None" in fn

    def test_only_a_first_generation_is_batched(self):
        # A retry or a completion pass happens because somebody is on the page pressing a
        # button, so it wants to be fast rather than cheap. It would also mean overwriting
        # a partial report — which holds analyses already paid for — with a placeholder.
        src = (BACKEND / "app" / "api" / "v1" / "reports.py").read_text()
        assert "settings.REPORT_BATCH_ENABLED" in src
        gate = src.split("settings.REPORT_BATCH_ENABLED")[1].split(")")[0]
        assert "existing_report is None" in gate
        assert "batch_job is None" in gate


class TestThePendingPlaceholderIsNotAFailedOne:
    def test_the_two_markers_are_distinct(self):
        from app.api.v1.reports import _BATCH_PENDING, _UNSCORED

        # They render the same 0/100 and mean opposite things. Sharing a marker would put
        # "Report Unavailable — try again" on a report that is on its way, and each retry
        # would spend one of three attempts against a failure that had not happened.
        assert _BATCH_PENDING != _UNSCORED

    def test_a_pending_report_regenerates_without_spending_an_attempt(self):
        from app.api.v1.reports import _BATCH_PENDING, should_regenerate

        regenerate, attempts = should_regenerate(
            {"generated_by": _BATCH_PENDING, "batch_id": "msgbatch_x"}
        )
        assert regenerate is True
        assert attempts == 0

    def test_a_pending_report_reports_a_job_status_and_no_unscored_reason(self):
        from app.api.v1.reports import _BATCH_PENDING, _build_report_response

        response = _build_report_response(
            _FakeReportRow({"generated_by": _BATCH_PENDING, "batch_id": "b"})
        )
        assert response.job_status == "processing"
        # The client branches on this to decide between "preparing" and "failed". A pending
        # report carrying an unscored_reason would draw the retry card.
        assert response.unscored_reason is None

    def test_an_ordinary_report_has_no_job_status(self):
        from app.api.v1.reports import _build_report_response

        response = _build_report_response(_FakeReportRow({"generated_by": "ai"}))
        assert response.job_status is None


class _FakeReportRow:
    """The columns _build_report_response reads. Not an ORM object, and does not need to be."""

    def __init__(self, raw: dict):
        self.id = __import__("uuid").uuid4()
        self.session_id = __import__("uuid").uuid4()
        self.overall_score = 0.0
        self.overall_score_label = "Preparing"
        self.executive_summary = "..."
        self.readiness_level = "needs_more_practice"
        self.strengths: list[str] = []
        self.weaknesses: list[str] = []
        self.topic_scores: dict = {}
        self.improvement_roadmap: list = []
        self.is_shared = False
        self.created_at = datetime.now(UTC)
        self.pdf_url = None
        self.raw_report = raw
