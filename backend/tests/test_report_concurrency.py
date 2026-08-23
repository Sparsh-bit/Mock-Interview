"""
Report generation must not hold a database connection while it waits on the model —
tests/test_report_concurrency.py

THE FAILURE THIS PREVENTS. The AI call is awaited, so it never blocked the event loop and
the endpoint always looked fine under light load. What it held was a pooled Postgres
connection, for the whole ~21 seconds, because Depends(get_db) opens the session when the
request starts and closes it when the response returns.

The pool is DB_POOL_SIZE + DB_MAX_OVERFLOW = 30 per process, so a sustained ~1.4 reports a
second exhausts it — and once exhausted every OTHER endpoint blocks for up to
DB_POOL_TIMEOUT waiting for a connection. A thousand candidates finishing interviews in the
same ten minutes is several times that rate, and the symptom would not have been "reports
are slow", it would have been the entire API timing out.

Both properties below are structural, so they are asserted against the source. A runtime
test would need a real 20-second provider call and a saturated pool to demonstrate
anything, and the thing being protected is the ORDER of two statements.
"""

from __future__ import annotations

import pathlib
import re

REPORTS = pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "reports.py"


def _generate_report_body() -> str:
    src = REPORTS.read_text()
    start = src.index("async def generate_report(")
    # Up to the next top-level def/decorator, so this cannot silently read the whole file.
    rest = src[start:]
    end = re.search(r"\n@router\.|\n(?:async )?def ", rest[1:])
    return rest[: end.start() + 1] if end else rest


class TestTheConnectionIsReleasedAcrossTheModelCall:
    def test_the_body_was_actually_found(self):
        # Guards both assertions below from passing vacuously if the function is renamed.
        body = _generate_report_body()
        assert "asyncio.wait_for" in body and len(body) > 2000, (
            "could not locate the generate_report body — fix this scanner before trusting "
            "the assertions below"
        )

    def test_a_commit_precedes_the_model_call(self):
        """
        The commit is what returns the connection to the pool. Its POSITION is the whole
        point: after it, the reads are done and the write below re-acquires lazily, so a
        report occupies a connection for milliseconds at each end instead of for the
        entire generation.

        This works only because the session factory sets expire_on_commit=False — see the
        companion assertion below. Without that, committing here would expire every ORM
        object already loaded and the prompt would be built from detached instances.
        """
        body = _generate_report_body()
        commit_at = body.find("await db.commit()")
        call_at = body.find("asyncio.wait_for")
        assert commit_at != -1, "no commit before the model call — the connection is held"
        assert commit_at < call_at, (
            "the commit that releases the pooled connection must come BEFORE the model "
            "call, or the connection is held for the whole generation and the pool "
            "becomes the bottleneck for every other endpoint"
        )

    def test_the_session_factory_does_not_expire_on_commit(self):
        # The mid-request commit above depends on this. If it ever flips to True, the
        # commit silently expires every object loaded so far and the failure appears as a
        # lazy-load error deep inside prompt building.
        from app.db.session import AsyncSessionFactory

        assert AsyncSessionFactory.kw["expire_on_commit"] is False


class TestConcurrencyIsBounded:
    def test_the_model_call_is_inside_a_semaphore(self):
        # Releasing the connection means a thousand concurrent requests can all reach the
        # provider instead of queuing on the pool — trading a database outage for a
        # rate-limit storm and a day's budget in minutes. The semaphore is the real queue.
        body = _generate_report_body()
        slots_at = body.find("_report_slots")
        call_at = body.find("asyncio.wait_for")
        assert slots_at != -1, "the model call is not bounded by a semaphore"
        assert slots_at < call_at, "the semaphore must be acquired before the model call"

    def test_the_limit_is_bounded_but_big_enough_for_a_cohort(self):
        """
        The upper bound was 8, justified by memory and spend. Both reasons were re-checked and
        neither holds at that number:

          MEMORY — an in-flight report holds a ~17k-token prompt, so twelve is well under a
          megabyte of text. That is not a limit worth defending.

          SPEND — concurrency does not change how much is spent, only how fast. The same
          reports are generated either way; what caps cost is AI_DAILY_BUDGET_USD, which is a
          real ceiling rather than a side effect of a queue length.

        What DOES bound it is the provider's rate limit: enough parallel completions and a 429
        comes back, which surfaces to the candidate as an unscored report. So there is still a
        ceiling — it is just much higher than 8, and the lower bound matters more. At 0 or 1
        the endpoint serialises and a drive queues for minutes; the generation budget covers
        queue time as well as generation, so a long queue means reports that never reach the
        model at all.
        """
        from app.core.config import settings

        assert 4 <= settings.REPORT_CONCURRENCY <= 24

    def test_waiting_for_a_slot_counts_against_the_time_budget(self):
        """
        wait_for must be INSIDE the semaphore, not outside it.

        If the timeout wrapped the acquire as well, a queued request would give up before
        it ever called the model. Inside, a candidate who waits too long for a slot gets
        the honest unscored placeholder with a retry — which is better than a request that
        hangs past the host gateway and returns a CORS-less 502 that tells them nothing.
        """
        body = _generate_report_body()
        assert body.find("_report_slots") < body.find("asyncio.wait_for")


class TestTheRateLimitChargesGenerationsNotReads:
    """
    The 429s reported from production.

    /reports/{id}/generate is idempotent and therefore doubles as the client's READ path —
    hooks/useData.ts::useReport POSTs to it rather than probing with a GET first, because a
    GET on a session with no report yet logs a 404 in the console that JavaScript cannot
    suppress.

    So when the limiter was a route DEPENDENCY it ran before the handler and charged every
    call, including the ones that just hand back a finished report. Six per hour then meant a
    candidate who opened their own completed report six times was locked out of generating a
    new one — the limit punishing the action it was never meant to police.

    The check now sits where the model call is about to happen. Everything above it returns
    free.
    """

    def test_the_limit_is_not_a_route_dependency(self):
        src = REPORTS.read_text()
        decorator = src[src.index('@router.post(\n    "/{session_id}/generate"') : src.index("async def generate_report(")]
        assert "_report_rate_limit" not in decorator and "rate_limiter" not in decorator, (
            "the rate limit is back on the route decorator, so it charges cached reads again "
            "— see this class's docstring for what that broke"
        )

    def test_the_limit_is_charged_after_the_cached_report_returns(self):
        body = _generate_report_body()
        cached_return = body.find("report_served_from_database")
        charge = body.find("enforce_limit(")
        model_call = body.find("asyncio.wait_for")

        assert cached_return != -1 and charge != -1, "could not locate both points"
        assert cached_return < charge, (
            "an already-generated report must be served BEFORE the limit is charged, or "
            "reading a finished report costs a generation"
        )
        assert charge < model_call, (
            "the limit must be charged BEFORE the model call, or it protects nothing"
        )

    def test_the_limit_allows_more_than_a_handful(self):
        # A generation that degrades to the unscored placeholder is legitimately retried, and
        # each retry is a real attempt. Too tight and the retry path is unusable.
        from app.core.config import settings

        assert settings.RATE_LIMIT_REPORT_PER_HOUR >= 10
