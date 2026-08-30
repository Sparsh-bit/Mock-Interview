"""
The report batch job, and the one rule it exists to guarantee — services/report/batch_job.py

A report submitted to the Batches API is a piece of work that has left the building. It will
be answered in minutes, or in twenty-four hours, or — if Anthropic errors it, expires it, or
the id is simply wrong — never. Meanwhile a candidate has finished their interview and is
looking at a page.

THE INVARIANT, and everything here is in service of it:

    A REPORT CAN NEVER BE PERMANENTLY STUCK.

That is not one check. Nothing that depends on a single mechanism is a guarantee, because the
mechanism itself can be the thing that fails. It is four, and they are independent:

  1. SUBMISSION FAILS -> nothing is recorded and the synchronous path runs in the same
     request. The candidate never knows a cheaper route was attempted. See api/v1/reports.py.

  2. ONE BATCH ATTEMPT PER SESSION, EVER. The job row is unique on session_id, and a session
     with a job that ended in any state other than `completed` never batches again — it goes
     synchronous for the rest of time. This is what makes a loop structurally impossible
     rather than merely unlikely: there is no counter to get wrong and no cooldown to
     mistune.

  3. A BATCH THAT NEVER ENDS IS ABANDONED. Past `max_wait_seconds` the job stops being the
     answer regardless of what the provider says, and rule 2 then routes the session
     synchronously. A provider that accepts a batch and goes quiet costs one wait, once.

  4. A BATCH WE CANNOT SEE IS ABANDONED TOO. Repeated failures to even retrieve the status —
     a deleted batch, a rotated key, an id from a different account — are counted, and past
     `max_lookup_failures` the job is abandoned. Without this, an unreachable batch would
     sit in `processing` forever, which is the exact failure mode the whole file exists to
     rule out.

WHY THIS IS PURE. Every function here takes the provider's answer and a clock and returns a
decision. No database, no HTTP, no `datetime.now()` reaching into the module from outside a
parameter. The state machine is the part that must be right in cases nobody can reproduce on
demand — an expired batch, a 24-hour stall, a provider that answers "canceling" — and pure
functions are the only way to test those cases at all.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

#: The custom_id of the summary part. There is exactly one per batch.
SUMMARY_PART = "summary"


def part_id(question_ids: Sequence[str]) -> str:
    """
    The custom_id for the analysis part covering exactly these questions, in this order.

    DERIVED FROM THE CONTENT, NOT FROM THE BATCH'S POSITION. `analysis:0`, `analysis:1` would
    have been simpler and would have been a real bug: the batches are planned over the
    questions that are still UNGRADED, so if anything grades a question between submission
    and collection — a synchronous fallback attempt, a completion pass — batch 1 no longer
    covers the same questions it covered when it was submitted. A positional id would then
    attach one set of answers' feedback to a different set of questions, silently, and the
    candidate would read a stranger's analysis under their own question.

    A digest of the question ids cannot do that. If the slice has changed, the id simply does
    not match anything in the collected results, and that part falls through to a synchronous
    call — the safe direction to be wrong in.
    """
    digest = hashlib.sha256("|".join(question_ids).encode("utf-8")).hexdigest()[:16]
    return f"analysis:{digest}"


class JobStatus(StrEnum):
    """
    Where a report's batch job stands. Stored as a string on `report_jobs.status`.

    Only `COMPLETED` is a success. The other two terminal states differ in cause, not in
    consequence — both send the session down the synchronous path — and they are kept
    apart because they need completely different operational responses. A run of FAILED is
    the provider rejecting work; a run of ABANDONED is the provider being slower than the
    deadline, which is a tuning question.
    """

    PROCESSING = "processing"
    COMPLETED = "completed"
    #: The provider ended the batch without usable results, or every part errored.
    FAILED = "failed"
    #: We stopped waiting. The batch may still be alive at the provider; we are no longer
    #: its audience.
    ABANDONED = "abandoned"

    @property
    def terminal(self) -> bool:
        return self is not JobStatus.PROCESSING


class Decision(StrEnum):
    """What a poll of a live job concluded."""

    #: Still in flight and still inside its deadline. Poll again later.
    WAIT = "wait"
    #: Ended at the provider. Fetch the results and build the report.
    COLLECT = "collect"
    #: Give up on the batch. The session goes synchronous from here.
    FALL_BACK = "fall_back"
    #: Already finished and already built. Nothing to do — and specifically NOT "wait",
    #: which is what this was first written as. A completed job answering WAIT would have
    #: the client polling a report it already has, forever.
    DONE = "done"


#: How long a batch may run before we stop being its audience.
#:
#: FIFTEEN MINUTES IS A PRODUCT DECISION, NOT A TECHNICAL ONE, and it is worth naming which.
#: Anthropic's own ceiling is 24 hours and most batches finish far inside an hour, so a longer
#: deadline would collect more batches and save more money. The limit here is what a person
#: who has just finished an interview will tolerate before "your report is being prepared"
#: stops sounding like a system that works. Past it they are better served by a report
#: generated synchronously at full price than by a cheaper one they have stopped waiting for.
DEFAULT_MAX_WAIT_SECONDS = 15 * 60

#: How many consecutive failures to even RETRIEVE the batch before giving up on it.
#:
#: Three, and not one, because a status lookup fails for two completely different reasons: a
#: momentary network blip, which the next poll fixes, and a batch that does not exist, which
#: no number of polls will fix. Retrying is right for the first and merely slow for the
#: second, so this is set where the cost of being wrong about a blip (three polls) is smaller
#: than the cost of abandoning a healthy batch (the whole 50% saving, on every report).
DEFAULT_MAX_LOOKUP_FAILURES = 3


@dataclass(frozen=True)
class JobView:
    """
    The stored job, as the state machine needs to see it.

    A plain snapshot rather than the ORM row, so this module cannot accidentally acquire a
    database dependency and so a test can construct any situation — including ones that take
    24 hours to occur naturally — in one line.
    """

    status: JobStatus
    submitted_at: datetime
    lookup_failures: int = 0
    max_wait_seconds: int = DEFAULT_MAX_WAIT_SECONDS
    max_lookup_failures: int = DEFAULT_MAX_LOOKUP_FAILURES

    def age_seconds(self, now: datetime) -> float:
        """
        How long this job has been in flight, never negative.

        Clamped at zero because `submitted_at` comes out of the database and `now` comes
        from this process, and the two are not the same clock. A host whose time is a few
        seconds behind the database would otherwise produce a negative age — harmless here,
        but it would read as a nonsense number in the logs at exactly the moment somebody is
        trying to work out why reports are slow.
        """
        return max(0.0, (now - self.submitted_at).total_seconds())

    def expired(self, now: datetime) -> bool:
        return self.age_seconds(now) >= self.max_wait_seconds

    def deadline(self) -> datetime:
        return self.submitted_at + timedelta(seconds=self.max_wait_seconds)


def decide(
    job: JobView,
    *,
    processing_status: str | None,
    now: datetime,
) -> Decision:
    """
    What to do with a live job, given what the provider just said.

    `processing_status` is None when the provider could not be reached at all — which is a
    different thing from the batch being unfinished, and is the case that would otherwise
    leave a job in `processing` forever.

    "ENDED" BEATS THE DEADLINE, and the order below is deliberate. A batch that has ended is
    collected however late it is — the results are already paid for, and discarding them to
    honour a deadline would be spending money in order to be punctual. But a batch that is
    still merely "in_progress" past its deadline is abandoned no matter how healthy it looks,
    because from the candidate's side "still working" and "never coming" are the same
    experience.
    """
    if job.status.terminal:
        # Nothing to decide. A terminal job is a fact, and re-polling it would be how a
        # completed report gets rebuilt or an abandoned one comes back to life.
        return Decision.DONE if job.status is JobStatus.COMPLETED else Decision.FALL_BACK

    if processing_status is None:
        # Could not reach the batch. Tolerated a few times, then abandoned — an
        # unreachable batch that is retried forever is a report stuck forever.
        if job.lookup_failures + 1 >= job.max_lookup_failures:
            return Decision.FALL_BACK
        return Decision.WAIT

    if processing_status == "ended":
        # Collected even past the deadline: see the docstring.
        return Decision.COLLECT

    if processing_status == "canceling":
        # Somebody cancelled it out of band. It will end with no usable results, and
        # waiting for that to be confirmed only delays the report.
        return Decision.FALL_BACK

    # "in_progress", or a status this SDK version does not know about. Treated as unfinished
    # rather than as an error, because an unrecognised status from a provider that is
    # plainly still working is not evidence of anything being wrong — the deadline below is
    # what bounds it either way.
    return Decision.FALL_BACK if job.expired(now) else Decision.WAIT


@dataclass(frozen=True)
class Collection:
    """What came back when an ended batch was read."""

    #: custom_id -> raw model text, for the parts that succeeded.
    succeeded: dict[str, str]
    #: custom_id -> why it did not, for the parts that did not.
    failed: dict[str, str]

    @property
    def any_usable(self) -> bool:
        return bool(self.succeeded)


def status_after_collection(collection: Collection) -> JobStatus:
    """
    Where a job lands once its results are in hand.

    PARTIAL IS COMPLETED, NOT FAILED, and that is the same judgement the synchronous path
    already makes. A report survives losing some of its analysis batches — the questions
    that were graded are shown, the rest are carried to the next attempt, and the summary
    can be derived from the scores that landed. Calling that "failed" would throw away
    grading that was done and paid for, and send the session back to full price to redo it.

    Only a batch where NOTHING came back is a failure, because there is genuinely nothing to
    build on and the synchronous path is the only route left.
    """
    return JobStatus.COMPLETED if collection.any_usable else JobStatus.FAILED


def may_batch(existing: JobView | None) -> bool:
    """
    Is this session allowed to use the Batches API?

    ONLY IF IT HAS NEVER TRIED. This is guarantee 2 from the module docstring, and it is
    stated as one line rather than as a retry policy on purpose. A session whose batch job
    failed, was abandoned, or is still in flight does not get another one:

      * still PROCESSING — a second batch would double the bill for one report and race the
        first one to write it.
      * FAILED or ABANDONED — whatever went wrong, the synchronous path is now the answer.
        Retrying the cheap route is how a report loops between two ways of not existing.
      * COMPLETED — the report exists. Nothing to generate.

    So batching is a single, cheap attempt per session, and every route out of it ends
    somewhere a report gets written.
    """
    return existing is None
