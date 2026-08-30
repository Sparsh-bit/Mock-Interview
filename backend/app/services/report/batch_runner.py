"""
Driving a report's batch job forward — services/report/batch_runner.py

The state machine in batch_job.py decides WHAT to do; this decides when, and does it. It is
the only place that touches both the provider and the `report_jobs` row, and it exists as its
own module for one reason: every path into it must be able to fail without a report failing.

WHO CALLS THIS, AND WHY BOTH.

  `POST /reports/{id}/generate` calls it before doing anything expensive. That is what makes
  the whole feature work without the frontend's cooperation: a candidate who closes the tab,
  comes back tomorrow and opens their report gets the finished batch collected on the spot.
  If the client never polls, nothing is lost — the results sit at the provider for 29 days.

  `GET /reports/{id}/job` calls it so the page can show progress. That endpoint is a
  convenience, not the mechanism. Nothing about correctness depends on anyone polling.

WHAT IT REFUSES TO DO. It never raises for a provider problem. A batch that cannot be
reached, cannot be read, or comes back empty resolves to a terminal job status and the caller
generates the report synchronously at full price. The expensive path always exists; this one
is an optimisation, and an optimisation that can break a report is not one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from app.services.ai import batch as ai_batch
from app.services.ai.base_provider import ProviderError, ProviderResponse
from app.services.report.batch_job import (
    Collection,
    Decision,
    JobStatus,
    JobView,
    decide,
    status_after_collection,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Advance:
    """What one attempt to move a job forward concluded."""

    status: JobStatus
    #: custom_id -> the model's raw text, for parts that came back usable. Empty unless the
    #: batch just ended, or had already ended and been collected.
    results: dict[str, str] = field(default_factory=dict)
    #: custom_id -> why it did not, for parts that failed. Kept so a report built from a
    #: partial batch can say which slice is missing rather than only that some is.
    failures: dict[str, str] = field(default_factory=dict)
    #: Provider counts, for the progress the page shows. Absent when unreachable.
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """Is there anything here to build a report out of?"""
        return bool(self.results)


def view_of(job) -> JobView:
    """
    A `report_jobs` row as the pure state machine sees it.

    `created_at` IS the submission time — the row is written in the same breath as the
    submit — so there is no separate `submitted_at` column to keep in step with it. One
    timestamp that cannot disagree with itself beats two that can.
    """
    from app.core.config import settings  # noqa: PLC0415

    submitted = job.created_at
    if submitted is not None and submitted.tzinfo is None:
        # Postgres returns timestamptz as aware, but a row constructed in a test or by an
        # older column definition may not be. Compared against an aware `now`, a naive value
        # raises TypeError — inside a poll, which would turn a slow batch into a 500.
        submitted = submitted.replace(tzinfo=UTC)
    return JobView(
        status=JobStatus(job.status),
        submitted_at=submitted or datetime.now(UTC),
        lookup_failures=job.lookup_failures or 0,
        max_wait_seconds=settings.REPORT_BATCH_MAX_WAIT_SECONDS,
    )


async def advance(db, job) -> Advance:
    """
    Poll the job's batch, collect it if it has ended, and write the outcome to the row.

    Commits nothing. The caller owns the transaction — `get_db` commits on success and rolls
    back on error — so a failure anywhere after this leaves the job exactly as it was and the
    next poll tries again, rather than recording a state change for work that did not happen.
    """
    now = datetime.now(UTC)
    view = view_of(job)

    if view.status.terminal:
        # Already decided. Return what is stored rather than asking the provider again: the
        # results were saved on the poll that collected them precisely so that a completed
        # job costs nothing to read.
        stored = _stored_results(job)
        return Advance(status=view.status, results=stored[0], failures=stored[1])

    processing_status: str | None = None
    counts: dict[str, int] = {}
    try:
        status = await ai_batch.poll(job.batch_id)
        processing_status = status.processing_status
        counts = status.counts
    except ProviderError as exc:
        # NOT RAISED. A status lookup fails for a blip or for a batch that does not exist,
        # and the two are indistinguishable from here — so it is counted, and `decide`
        # abandons the job once the count says this is not a blip.
        logger.warning(
            "report_batch_poll_failed",
            batch_id=job.batch_id,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
            lookup_failures=job.lookup_failures,
        )

    decision = decide(view, processing_status=processing_status, now=now)

    if decision is Decision.WAIT:
        if processing_status is None:
            job.lookup_failures = (job.lookup_failures or 0) + 1
        elif job.lookup_failures:
            # A successful poll clears the count. Three failures spread over an hour are a
            # flaky network; three in a row are a batch that is not there, and only the
            # second is worth abandoning a job over.
            job.lookup_failures = 0
        return Advance(status=JobStatus.PROCESSING, counts=counts)

    if decision is Decision.FALL_BACK:
        job.status = JobStatus.ABANDONED.value
        job.error = (
            f"gave up after {int(view.age_seconds(now))}s "
            f"(provider status: {processing_status or 'unreachable'})"
        )
        logger.warning(
            "report_batch_abandoned",
            batch_id=job.batch_id,
            age_s=int(view.age_seconds(now)),
            provider_status=processing_status or "unreachable",
            max_wait_s=view.max_wait_seconds,
        )
        return Advance(status=JobStatus.ABANDONED, counts=counts)

    # Decision.COLLECT — the batch has ended and its results are waiting.
    return await _collect(db, job, counts)


async def _collect(db, job, counts: dict[str, int]) -> Advance:
    """Read an ended batch, record what it cost, and store what it produced."""
    try:
        raw = await ai_batch.collect(job.batch_id)
    except ProviderError as exc:
        # The batch ended but could not be read. Counted like a failed status lookup rather
        # than abandoned outright — reading results is a separate call that can blip on its
        # own, and the results stay available at the provider for 29 days.
        job.lookup_failures = (job.lookup_failures or 0) + 1
        logger.warning(
            "report_batch_results_failed",
            batch_id=job.batch_id,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        if (job.lookup_failures or 0) >= JobView(
            status=JobStatus.PROCESSING, submitted_at=datetime.now(UTC)
        ).max_lookup_failures:
            job.status = JobStatus.ABANDONED.value
            job.error = f"batch ended but results could not be read: {str(exc)[:200]}"
            return Advance(status=JobStatus.ABANDONED, counts=counts)
        return Advance(status=JobStatus.PROCESSING, counts=counts)

    results: dict[str, str] = {}
    failures: dict[str, str] = {}
    for custom_id, item in raw.items():
        if isinstance(item, ProviderResponse):
            results[custom_id] = item.content
        else:
            failures[custom_id] = str(item)

    await _record_batch_usage(job, raw)

    collection = Collection(succeeded=results, failed=failures)
    job.status = status_after_collection(collection).value
    job.lookup_failures = 0
    if failures:
        job.error = ", ".join(f"{cid}: {why}" for cid, why in sorted(failures.items()))[:1000]

    # STORED ON THE ROW, so collection happens exactly once. The provider keeps results for
    # 29 days, but reading them again on every page view would be a request per view for
    # bytes we already have — and, more importantly, the report is built from these in a
    # LATER step, which must not depend on the provider still being reachable by then.
    parts = dict(job.parts or {})
    for custom_id, text in results.items():
        entry = dict(parts.get(custom_id) or {})
        entry["raw"] = text
        parts[custom_id] = entry
    for custom_id, why in failures.items():
        entry = dict(parts.get(custom_id) or {})
        entry["error"] = why
        parts[custom_id] = entry
    job.parts = parts

    logger.info(
        "report_batch_collected",
        batch_id=job.batch_id,
        status=job.status,
        succeeded=len(results),
        failed=len(failures),
    )
    return Advance(
        status=JobStatus(job.status), results=results, failures=failures, counts=counts
    )


async def _record_batch_usage(job, raw: dict[str, ProviderResponse | str]) -> None:
    """
    Put the batch's real cost in the `ai_usage` ledger, per part, at the batch rate.

    WITHOUT THIS THE LEDGER WOULD SAY REPORTS BECAME FREE. Every synchronous call records
    itself inside generate_structured; a batched one has no such moment, because the request
    and the response are hours apart and the response arrives in somebody else's HTTP call.
    An unrecorded batch would make the most expensive feature in the product vanish from the
    one document that is supposed to be re-derived from that ledger.
    """
    from app.services.ai.usage import record_call  # noqa: PLC0415
    from app.services.report.batch_job import SUMMARY_PART  # noqa: PLC0415

    for custom_id, item in raw.items():
        if not isinstance(item, ProviderResponse):
            continue
        feature = (
            "report_generation" if custom_id == SUMMARY_PART else "report_analysis"
        )
        await record_call(
            feature=feature,
            provider=job.provider,
            response=item,
            cost_tier="balanced",
            outcome="ok",
        )


def _stored_results(job) -> tuple[dict[str, str], dict[str, str]]:
    """What a previous collection saved on the row: (usable raw text, failures)."""
    results: dict[str, str] = {}
    failures: dict[str, str] = {}
    for custom_id, entry in (job.parts or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("raw"):
            results[custom_id] = entry["raw"]
        elif entry.get("error"):
            failures[custom_id] = str(entry["error"])
    return results, failures
