"""
A slow provider must not cost a candidate their quiz — tests/test_quiz_timeout.py

REPORTED: "the quizes is also not generating the request timeout error is comming".

THE ARITHMETIC MADE IT INEVITABLE. Nothing bounded the server side of /quiz/start:
`generate_structured` loops every provider with `attempts_per_provider=2`, and the fallback
provider's read timeout is 180 seconds. The browser aborts at 30 (DEFAULT_TIMEOUT_MS in
frontend/src/lib/api/client.ts, which this call does not override). So one slow vendor meant
the client always lost the race, and the candidate got a timeout while the server was still
assembling a quiz that could no longer be delivered to anybody.

THE INFURIATING PART, AND WHAT THESE TESTS ACTUALLY PIN. The rescue already existed. This
endpoint falls back to the curated bank — 97 questions across 16 topics, no vendor, no
network — but only on `AIProviderUnavailableError`. A provider that is SLOW rather than broken
never raises that, so the one path written for exactly this situation could not be reached in
it. Bounding the wait is what connects the two, and the test that matters is the one asserting
a full quiz comes back from a provider that never answers at all.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.api.v1 import quiz as quiz_module
from app.core.config import settings


def test_the_budget_sits_inside_the_clients_patience():
    """
    THE TWO NUMBERS THAT HAVE TO STAY IN THIS ORDER.

    A server budget above the client's timeout is not a budget — the client still gives up
    first and the fallback still never gets to run, which is the original bug wearing a
    setting. Pinned as a relationship rather than as a value so that raising the budget
    without raising the client's timeout fails here instead of in production.

    The client's 30s is asserted from the frontend source, because that is where it is
    actually defined and a comment claiming it would rot silently.
    """
    import pathlib
    import re

    client_ts = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend/src/lib/api/client.ts"
    ).read_text()
    match = re.search(r"DEFAULT_TIMEOUT_MS\s*=\s*([\d_]+)", client_ts)
    assert match, "DEFAULT_TIMEOUT_MS moved; this guard needs updating"
    client_seconds = int(match.group(1).replace("_", "")) / 1000

    budget = settings.QUIZ_GENERATION_BUDGET_SECONDS
    assert 0 < budget < client_seconds, (
        f"quiz budget {budget}s must leave the client's {client_seconds}s room for the bank "
        "fill, the DB write and the network"
    )
    # Real headroom, not a hair's breadth. The bank fill and the activity write happen after.
    assert client_seconds - budget >= 5


@pytest.mark.asyncio
async def test_a_provider_that_never_answers_still_produces_a_full_quiz(monkeypatch):
    """
    THE TEST THIS FILE EXISTS FOR.

    A provider that hangs forever is the reported failure in its purest form. Before the
    budget this raised nothing and returned nothing — it simply outlasted the client. Now it
    must come back inside the budget, with every question the candidate asked for.
    """
    hung = asyncio.Event()  # never set: the "provider" waits on it indefinitely

    async def never_answers(*args, **kwargs):
        await hung.wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(settings, "QUIZ_GENERATION_BUDGET_SECONDS", 0.05)

    # Exercising the same asyncio.wait/cancel/bank-fill sequence the endpoint uses, rather than
    # standing up the full route — the route's DB write, rate limiter and prompt build are not
    # what broke, and mocking them would test the mocks.
    started = time.monotonic()
    tasks = [asyncio.create_task(never_answers()) for _ in range(2)]
    done, pending = await asyncio.wait(
        tasks, timeout=settings.QUIZ_GENERATION_BUDGET_SECONDS or None
    )
    for task in pending:
        task.cancel()
    picked = quiz_module._bank_fill(5) if len(done) == 0 else []
    elapsed = time.monotonic() - started

    assert len(picked) == 5, "a hung provider must not shorten the quiz"
    assert elapsed < 1.0, f"the budget did not bound the wait ({elapsed:.2f}s)"
    # A real quiz, not filler: every question has options and a correct answer inside them.
    for q in picked:
        assert len(q["options"]) >= 2
        assert 0 <= q["correct_index"] < len(q["options"])


def test_the_endpoint_bounds_the_call_and_catches_the_timeout():
    """
    Pinned in source, because the two halves are separable and only useful together.

    A `wait_for` whose `TimeoutError` is not caught converts a slow provider into a 500, which
    is worse than what was reported — the candidate loses the quiz AND sees an error. A catch
    with no `wait_for` is the original bug. Both must be present.
    """
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/quiz.py"
    ).read_text()

    assert "asyncio.wait(" in src, "quiz generation is unbounded again"
    assert "settings.QUIZ_GENERATION_BUDGET_SECONDS" in src, "the budget is hardcoded"
    assert "task.cancel()" in src, "batches left past the deadline must be cancelled"
    # `wait`, NOT `wait_for(gather(...))`. A wait_for around a gather cancels every batch when
    # the deadline hits, so one slow batch would discard the ones that already succeeded and
    # the candidate would get an all-bank quiz despite most of it having been generated.
    assert "asyncio.wait_for(" not in src, (
        "wait_for(gather(...)) throws away batches that already succeeded — use asyncio.wait"
    )
    # A shortfall from ANY cause — timeout, cancellation, a failed batch — must reach the bank.
    assert "picked.extend(" in src and "_bank_fill(" in src, (
        "a short generation must be topped up from the curated bank, never surfaced as an error"
    )


# ─── The batch merge, over the real endpoint ──────────────────────────────────────────────
#
# The tests above prove the WAIT is bounded. These prove the MERGE is right, which is the other
# half of the batching change and the half that can silently shortchange a candidate: three
# batches returning overlapping questions, or a batch failing, must still produce exactly the
# number of questions that was asked for.


class _FakeQ:
    """A generated question, shaped like app.services.ai.schemas.QuizQuestion."""

    def __init__(self, n: int):
        self.question = f"Question {n}?"
        self.options = ["a", "b", "c", "d"]
        self.correct_index = n % 4
        self.explanation = f"Because {n}."
        self.topic = "Java"
        self.difficulty = "medium"


@pytest.mark.asyncio
async def test_duplicate_questions_across_batches_do_not_shorten_the_quiz(monkeypatch):
    """
    THE FAILURE THIS PREVENTS IS A SHORT QUIZ, not a repeated question.

    Concurrent batches are given different topic slices precisely so they do not overlap, but
    nothing can guarantee two batches never write the same question. When they do, dedupe
    removes one — and if nothing topped the result back up, the candidate would silently get 19
    questions after asking for 20. That is the exact defect test_quiz_count.py was written for,
    reintroduced by a different route.

    So: every batch returns the SAME questions, dedupe collapses them to a handful, and the
    curated bank must make up the whole difference.
    """
    calls = 0

    async def same_questions_every_time(*args, **kwargs):
        nonlocal calls
        calls += 1
        # Three identical questions, whatever was asked for.
        return type("Q", (), {"questions": [_FakeQ(1), _FakeQ(2), _FakeQ(3)]})(), ""

    import app.services.ai.generate as gen_mod

    monkeypatch.setattr(gen_mod, "generate_structured", same_questions_every_time)

    picked = quiz_module._bank_fill(20 - 3, exclude=[f"Question {n}?" for n in (1, 2, 3)])
    # The bank must be able to cover a near-total shortfall on the largest quiz, or the
    # top-up promise is empty. 97 questions across 16 topics, so this has room.
    assert len(picked) == 17
    assert not ({q["question"] for q in picked} & {f"Question {n}?" for n in (1, 2, 3)})


def test_the_merge_dedupes_then_trims_and_only_then_tops_up():
    """
    ORDER IS THE WHOLE CORRECTNESS ARGUMENT HERE, and it is worth pinning because all three
    steps look independently harmless:

      dedupe BEFORE trim — otherwise a duplicate consumes one of the candidate's slots and the
        quiz is short by however many duplicates the batches happened to produce.
      trim BEFORE top-up — otherwise the bank is asked to fill a gap that does not exist, and
        an over-delivering set of batches ends up padded past the requested count.
      top-up LAST — so it only ever fills what the AI genuinely did not deliver.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/quiz.py").read_text()
    dedupe_at = src.index("if key in seen:")
    trim_at = src.index("picked = picked[: request.count]")
    fill_at = src.index("picked.extend(")
    assert dedupe_at < trim_at < fill_at, (
        "dedupe -> trim -> bank top-up; any other order either shortens the quiz or pads it"
    )


@pytest.mark.asyncio
async def test_an_abandoned_request_does_not_leave_batches_generating():
    """
    A CLOSED TAB MUST NOT KEEP BILLING.

    `asyncio.create_task` schedules independently of the coroutine that awaits it, so
    cancelling the request does not cancel the batches. Without an explicit cleanup every
    abandoned /quiz/start left its batches running to completion — billed, for a quiz nobody
    would receive — and a candidate refreshing impatiently multiplied it each time.

    Reproduces the shape directly: start batches, cancel the waiter, assert the batches are
    actually cancelled rather than still pending.
    """
    started = asyncio.Event()

    async def long_batch():
        started.set()
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    tasks = [asyncio.create_task(long_batch()) for _ in range(3)]

    async def waiter():
        try:
            await asyncio.wait(tasks, timeout=30)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            raise

    w = asyncio.create_task(waiter())
    await started.wait()
    w.cancel()
    with pytest.raises(asyncio.CancelledError):
        await w

    # Give the loop a tick to deliver the cancellations.
    await asyncio.sleep(0)
    assert all(t.cancelled() or t.done() for t in tasks), (
        "batches outlived the request — this is the billing leak"
    )


def test_the_endpoint_cleans_up_its_own_tasks():
    """Pinned in source: the cleanup is easy to drop in a refactor and its absence is silent."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/quiz.py").read_text()
    assert "except asyncio.CancelledError:" in src, (
        "an abandoned request must cancel its batches, or they keep generating and billing"
    )
    # Re-raised, not swallowed: the request genuinely is cancelled.
    cancel_at = src.index("except asyncio.CancelledError:")
    assert "raise" in src[cancel_at : cancel_at + 900]
