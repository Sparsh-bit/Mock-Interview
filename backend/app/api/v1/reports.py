"""
Report Endpoints — api/v1/reports.py

GET    /api/v1/reports/{session_id}           — Get or generate report for session
POST   /api/v1/reports/{session_id}/generate  — Trigger AI report generation
GET    /api/v1/reports/{report_id}/export/pdf — Download PDF export
PATCH  /api/v1/reports/{report_id}/share      — Toggle report sharing
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from time import perf_counter

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import settings
from app.core.rate_limit import enforce_limit
from app.core.security import CurrentUser
from app.db.redis import CacheKeys, get_redis
from app.db.session import AsyncSession, get_db
from app.events import ReportGeneratedEvent, ReportGeneratedPayload, get_event_emitter
from app.events.emitter import EventEmitter
from app.services.prep.study_resources import attach_to_roadmap
from app.services.progress.rating import tier_for
from app.services.progress.recorder import record_round

logger = structlog.get_logger(__name__)
router = APIRouter()

#: Wall-clock ceiling on AI report generation, chosen from how long the process
#: has been running.
#:
#: A flat 50s was too tight and it was the reason reports came back "Pending". A
#: complete 20-answer report — four dimension scores and twenty question analyses —
#: was MEASURED at 47.9 seconds. So the flat budget was clearing the real cost by
#: two seconds, and any interview slightly longer, or any slower moment on the
#: provider, fell off the edge into the unscored fallback. Every retry then hit the
#: same wall, so a long interview could never produce a finished report at all.
#:
#: The constraint is the host's gateway timeout (~100s on Render), which applies to
#: the WHOLE request including a cold start. That is why the budget was flat: a
#: cold start costs ~37s, so 37 + 50 = 87s was the only safe assumption.
#:
#: But cold is the exception, not the rule, so the headroom can be spent when it is
#: genuinely there:
#:
#:   cold:  37 + 50 = 87s   — unchanged, proven safe
#:   warm:  1.5 + 85 = 87s  — same ceiling, 35 more seconds of actual work
#:
#: Both land in the same place against the gateway. Exceeding the budget is still not a
#: failure: the handler falls back to the honest unscored report, which the candidate can
#: regenerate.
#:
#: WHICH CASE ARE WE IN? This used to be "process uptime < 120s means cold", and that
#: proxy is wrong in a way that shows up as reports timing out for no reason. A cold start
#: is paid by the ONE request that triggers the boot — its gateway timer started 37s before
#: our code ran. A request arriving 30 seconds later did not trigger anything: the process
#: was already up, so its timer started when IT arrived, and it has the full window. Under
#: the uptime rule that request got 50s instead of 85s purely because the container had
#: been restarted recently, which is exactly when a restart storm makes reports fail. It
#: also made the test suite flaky: a full run finishes inside 120s, so every report in it
#: was scored against the cold budget while the app was thoroughly warm.
#:
#: So the signal is "has this process finished serving a request yet" — which is precisely
#: the boot-triggering request and nothing else.
_REPORT_AI_BUDGET_COLD_SECONDS = 50.0
_REPORT_AI_BUDGET_WARM_SECONDS = 85.0

#: Flipped true once this process has completed any request. Set by the request middleware
#: in main.py, so it does not depend on a report being the first thing served.
_served_a_request = False


def mark_request_served() -> None:
    """Called once per request by the middleware; only the first call matters."""
    global _served_a_request
    _served_a_request = True

#: How many reports may be generating at once, per process.
#:
#: The queue that replaced the accidental one. Report generation used to hold a pooled
#: Postgres connection for its whole ~21s, so the 30-connection pool was itself the
#: limiter — badly, because exhausting it stalled every OTHER endpoint too. With the
#: connection released across the model call (see generate_report) a thousand concurrent
#: requests could all reach the provider at once, which trades a database outage for a
#: rate-limit storm and a day's budget spent in minutes.
#:
#: 4 is chosen against the numbers rather than picked: a report is ~21s, so four slots
#: sustain roughly 11 reports a minute per process, which is a busy drive; and four
#: in-flight ~17k-token prompts is bounded memory. Raise it with replica count, not
#: instead of it.
#: Read from settings so a drive that still queues can be widened without a deploy. See the
#: note on REPORT_CONCURRENCY for the arithmetic that set the default.
_report_slots = asyncio.Semaphore(settings.REPORT_CONCURRENCY)


def report_ai_budget_seconds() -> float:
    """
    How long AI report generation may run.

    The tighter budget applies only to a request that may itself have paid the container
    cold start — i.e. the first one this process serves. Everything after that has the
    full gateway window available. See the note above _REPORT_AI_BUDGET_COLD_SECONDS.
    """
    return (
        _REPORT_AI_BUDGET_WARM_SECONDS if _served_a_request else _REPORT_AI_BUDGET_COLD_SECONDS
    )

#: Marker for the placeholder report written when AI scoring is unavailable. It
#: is never a final result: generation retries and replaces it.
_UNSCORED = "unscored_fallback"

#: How many times a placeholder may retry AI scoring before it stops trying.
#:
#: Bounds spend. The client requests the report on every page view, and each
#: retry is a separately billed model call — so an unbounded retry would turn a
#: persistent provider outage into an open-ended bill just from someone reloading
#: the page. After this many failures the stored placeholder is served as-is.
_MAX_UNSCORED_ATTEMPTS = 3

#: Which generation strategy produced a stored report. BUMP THIS whenever a change could make
#: a previously-failing report succeed.
#:
#: WHY IT EXISTS. Twice now a bug has made report scoring fail for a whole population of
#: candidates, and both times the fix shipped and rescued nobody — because the retry cap and
#: the cooldown had already condemned their placeholders, so "Generate again" did nothing and
#: the report sat at 0/100 forever. The fix was correct and the affected reports stayed dead.
#:
#: A placeholder written by an OLDER strategy than the one running is not out of attempts: its
#: attempts were spent against code that no longer exists. So it gets a fresh set, once, the
#: next time anybody opens it — no SQL, no migration, no script anybody has to remember to
#: run, and nobody has to go and find the affected sessions.
#:
#: It cannot loop: the retry stamps the current strategy whether it succeeds or fails, so a
#: stale row is rescued exactly once per bump.
_GENERATION_STRATEGY = "split-v1"

#: Between two questions in the transcript handed to the model. Module scope because the
#: summary call and every analysis batch must format the transcript the SAME way: the rubric
#: is provider-cached on the exact bytes of the system block, and a batch that separated
#: questions differently would read a different transcript from the one the summary read.
_TRANSCRIPT_SEPARATOR = "\n\n---\n\n"

#: Output-token budget for report generation, as (fixed, per-question).
#:
#: A single constant cannot be right here. The report's largest section is
#: `question_analysis`, which carries one entry PER QUESTION, so the response
#: grows with the interview: a 6-question session needs far less than a
#: 16-question one. A fixed ceiling therefore either wastes money on short
#: sessions or truncates long ones -- and truncation is not a soft failure. The
#: JSON is cut mid-object, validation rejects it, and the candidate gets an
#: unscored placeholder instead of a report. That is exactly what happened: a
#: flat 2600 (clamped to 4096 by the provider) against a measured requirement of
#: ~5.1k output tokens for 16 questions, so every long interview failed.
#:
#: Calibrated against a real 16-question generation (measured 5078 output
#: tokens): 1500 + 16 * 260 = 5660, ~11% headroom. Do not tune these by
#: intuition -- measure, because being 1 token short costs the whole report.
_REPORT_TOKENS_FIXED = 1500
# Raised from 260. question_analysis is now required at one entry per question,
# and each entry carries the question, a quality verdict, a score, the missing
# concepts and a model answer summary — measured at 90-140 output tokens. At 260
# per question the whole response competed for room with the summary sections and
# the JSON truncated, which is what `ai_json_extraction_failed` in the logs was.
_REPORT_TOKENS_PER_QUESTION = 340

#: Ceiling on the computed budget, so a pathological session (hundreds of rows)
#: cannot request an unbounded response.
_REPORT_TOKENS_MAX = 12_000


#: The four competencies the report's headline panel renders. A report missing any
#: of them draws a blank panel.
_REQUIRED_DIMENSIONS = (
    "technical_accuracy",
    "answer_completeness",
    "communication_clarity",
    "confidence",
)


#: Why a report came back unscored. The candidate sees a different sentence for each,
#: because they mean different things and imply different actions.
_REASON_USER_QUOTA = "user_quota"
_REASON_SERVICE_LIMIT = "service_limit"
_REASON_TIMEOUT = "timeout"
_REASON_PROVIDER = "provider_unavailable"


def _classify_failure(exc: BaseException) -> str:
    """
    Turn a generation failure into the reason a candidate should be shown.

    The order matters: UserBudgetExceededError subclasses BudgetExceededError, so the
    more specific one has to be tested first or every personal allowance would be
    reported as a service-wide outage — which is both wrong and alarming.

    Imported locally because core report generation should not fail to import if the
    provider module is unavailable.
    """
    try:
        from app.services.ai.anthropic_provider import (  # noqa: PLC0415
            BudgetExceededError,
            UserBudgetExceededError,
        )
    except Exception as import_exc:  # noqa: BLE001
        # NAMED import_exc, NOT exc. `exc` is this function's PARAMETER — the exception being
        # classified — and binding the same name here shadows it, then Python deletes the name
        # at the end of the except block, so every read below it fails. mypy caught it; a test
        # would not have, because this branch only runs if the billing import itself breaks.
        #
        # The log matters because this function decides WHY a report could not be scored, and
        # it used to lose the one piece of evidence that answers that. The returned reason is
        # what the candidate sees; this line is what the operator sees, and they are not the
        # same audience.
        logger.warning(
            "report_scoring_reason_undetermined",
            error_type=type(import_exc).__name__,
            error=str(import_exc)[:300] or type(import_exc).__name__,
        )
        return _REASON_PROVIDER

    # AIProviderUnavailableError wraps the last provider error; check the chain.
    seen: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and cur not in seen:
        seen.append(cur)
        if isinstance(cur, UserBudgetExceededError):
            return _REASON_USER_QUOTA
        if isinstance(cur, BudgetExceededError):
            return _REASON_SERVICE_LIMIT
        cur = cur.__cause__ or cur.__context__

    if isinstance(exc, TimeoutError):
        return _REASON_TIMEOUT
    return _REASON_PROVIDER


def _report_is_complete(report, answered: int) -> bool:
    """
    Is this report actually usable, or just schema-valid?

    Pydantic accepts a report with no dimension_scores and no question_analysis
    because both default to empty. Schema-valid and useless are different things,
    and only this check can tell them apart.

    question_analysis is required to cover most of the interview rather than all
    of it: demanding an exact match would reject a report that analysed 15 of 16
    answers, and 15 is far better for the candidate than the unscored fallback.
    Two thirds is the line — below that the model has summarised rather than
    analysed.
    """
    dims = report.dimension_scores or {}
    if not all(k in dims for k in _REQUIRED_DIMENSIONS):
        logger.warning(
            "ai_report_missing_dimensions",
            got=sorted(dims),
            required=list(_REQUIRED_DIMENSIONS),
        )
        return False

    qa = report.question_analysis or []
    if answered and len(qa) < max(1, (answered * 2) // 3):
        logger.warning(
            "ai_report_incomplete_question_analysis",
            got=len(qa),
            answered=answered,
        )
        return False
    return True


def report_token_budget(question_count: int) -> int:
    """
    Output-token budget for a report covering ``question_count`` questions.

    Scales with the interview because the response does. Never returns less than
    the fixed part, so a session with no recorded answers still gets a budget
    large enough for the summary sections.
    """
    count = max(0, question_count)
    budget = _REPORT_TOKENS_FIXED + count * _REPORT_TOKENS_PER_QUESTION
    return min(budget, _REPORT_TOKENS_MAX)


def should_regenerate(raw_report: dict | None) -> tuple[bool, int]:
    """
    Decide whether a stored report warrants another (billed) AI scoring call.

    Returns ``(regenerate, attempts_already_made)``.

    This is the whole cost policy for report generation, in one place:

    * A real scored report is final — serve it from the database, forever, for
      free. Generation is called on every page view, so this is what keeps a
      report from being re-billed every time someone opens it.
    * An unscored placeholder is not a result. Its own text tells the candidate
      to retry, so it is retried and replaced in place.
    * ...but only ``_MAX_UNSCORED_ATTEMPTS`` times. A provider outage must not
      become an open-ended bill funded by page reloads.
    """
    raw = raw_report or {}
    if raw.get("generated_by") != _UNSCORED:
        return False, 0
    # SANITISED FIRST. `raw_report` is JSONB and can hold anything a past version wrote — a
    # string "3", a float, a list, NaN. The cooldown check below compares it to an int, so
    # coercing after that check would turn hostile stored data into a TypeError and a 500 on
    # the report page. Treating anything unusable as a first attempt is the safe reading, and
    # the cap still applies from there.
    #
    # `bool` is excluded explicitly because it is a subclass of int in Python, so True would
    # otherwise read as "one attempt".
    raw_attempts = raw.get("unscored_attempts", 0)
    attempts = (
        raw_attempts
        if isinstance(raw_attempts, int)
        and not isinstance(raw_attempts, bool)
        and raw_attempts >= 0
        else 0
    )

    # ── A PLACEHOLDER FROM AN OLDER STRATEGY IS NOT OUT OF ATTEMPTS ───────────────────────
    #
    # Its attempts were spent against code that has since changed, so counting them against
    # the new code condemns exactly the population a fix was written for. See the note on
    # _GENERATION_STRATEGY. This is checked BEFORE the cap and the cooldown deliberately:
    # both of those are about spend on a strategy that is still failing, and this one is not
    # that strategy.
    if raw.get("strategy") != _GENERATION_STRATEGY:
        logger.info(
            "unscored_report_retried_after_strategy_change",
            stored=str(raw.get("strategy"))[:32],
            current=_GENERATION_STRATEGY,
            attempts_forgiven=attempts,
        )
        return True, 0

    # ── THE CAP RESETS, RATHER THAN CONDEMNING THE SESSION ────────────────────────────────
    #
    # This used to return `attempts < _MAX_UNSCORED_ATTEMPTS` and nothing else, which made
    # three failures permanent: the endpoint then served the placeholder from the database
    # forever with no model call, so "Generate again" did nothing and the report sat at 0/100
    # for good. An unscored report is also deliberately never paywalled, so the unlock could
    # never appear either — one transient failure took away both the report and the sale.
    #
    # A reload storm is the expensive case and it happens in SECONDS, so a cooldown stops it
    # just as well as a lifetime cap does. Past the cooldown the attempt counter is treated as
    # spent rather than binding, which lets a session recover once whatever broke has passed —
    # and recovers every already-affected candidate without anybody going to find them.
    if attempts >= _MAX_UNSCORED_ATTEMPTS:
        cooldown = settings.REPORT_UNSCORED_RETRY_COOLDOWN_MINUTES
        last_at = raw.get("unscored_last_at")
        if cooldown <= 0:
            # Expiry switched off deliberately. The old permanent cap.
            return False, attempts
        if not last_at:
            # ── A PLACEHOLDER FROM BEFORE THIS FIELD EXISTED. RETRY IT. ────────────────────
            #
            # This returned False, and that single line kept every already-broken report dead
            # forever — which is the whole population the cooldown was added to rescue. Their
            # placeholders were written before `unscored_last_at` existed, so they carry no
            # timestamp, so they could not be aged, so they were never retried. The fix shipped
            # and fixed nothing for anybody already affected.
            #
            # A missing timestamp is not unknown age: it means the row predates the deploy that
            # started writing the field, so it is necessarily older than any cooldown. Treating
            # it as retryable is the accurate reading, not a lenient one.
            #
            # The reload-storm risk this used to guard is one extra attempt per legacy report:
            # the retry writes a timestamp, and every decision after that is made on real age.
            return True, 0
        try:
            last = datetime.fromisoformat(str(last_at))
        except (ValueError, TypeError):
            # UNPARSEABLE IS TREATED AS UN-AGEABLE, WHICH MEANS RETRY — the same reading as a
            # missing timestamp above, and for the same reason. `raw_report` is JSONB and can
            # hold anything a past version wrote; refusing on garbage would strand exactly the
            # rows whose history we cannot read, permanently, for a data problem that is ours
            # rather than the candidate's. The retry overwrites it with a valid timestamp, so
            # this can only ever happen once per row.
            logger.warning("unscored_last_at_unparseable", value=str(last_at)[:64])
            return True, 0
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if datetime.now(UTC) - last >= timedelta(minutes=cooldown):
            # Fresh set of attempts. Returning 0 rather than the old count is what makes this
            # a reset instead of a single grudging extra try.
            return True, 0
        return False, attempts
    return attempts < _MAX_UNSCORED_ATTEMPTS, attempts


# ─── Schemas ──────────────────────────────────────────────────────────────────


class TopicScoreItem(BaseModel):
    topic: str
    score: float


class ImprovementResource(BaseModel):
    type: str
    title: str
    url: str | None = None
    author: str | None = None


class ImprovementItem(BaseModel):
    priority: int
    topic: str
    current_score: float
    target_score: float
    study_hours_estimate: int
    resources: list[ImprovementResource]


class QuestionAnalysisResponseItem(BaseModel):
    question_id: str
    question: str
    answer_quality: str
    score: float
    missing_concepts: list[str]
    ideal_answer_summary: str


class ReportResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    overall_score: float
    overall_score_label: str
    executive_summary: str
    readiness_level: str
    readiness_reasoning: str
    strengths: list[str]
    weaknesses: list[str]
    topic_scores: dict[str, float]
    dimension_scores: dict[str, float]
    performance_percentile: int
    question_analysis: list[QuestionAnalysisResponseItem]
    improvement_roadmap: list[ImprovementItem]
    is_shared: bool
    created_at: datetime
    pdf_url: str | None
    delivery: dict | None = None
    previous: dict | None = None
    #: Null on a real report. On an unscored one, WHY — "user_quota",
    #: "service_limit", "timeout" or "provider_unavailable". The client shows a
    #: different sentence for each, because one generic "temporarily unavailable"
    #: covering all four tells a candidate who has used their day's practice the same
    #: thing as one hitting an outage, and only one of those has an action.
    unscored_reason: str | None = None


# ─── Endpoints ────────────────────────────────────────────────────────────────


class ActivityItem(BaseModel):
    id: uuid.UUID
    activity_type: str
    title: str
    score: float
    details: dict | None
    created_at: datetime


@router.get("/activity/all", response_model=list[ActivityItem])
async def list_activity(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
):
    """
    Unified history feed: every activity the candidate has completed —
    interviews, group discussions, communication rounds, and quizzes — newest
    first, so the reports page can show everything they've done.
    """
    from app.models.activity import ActivityLog  # noqa: PLC0415

    rows = await db.scalars(
        select(ActivityLog)
        .where(ActivityLog.user_id == current_user.user_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    return [
        ActivityItem(
            id=a.id,
            activity_type=a.activity_type,
            title=a.title,
            score=a.score,
            details=a.details,
            created_at=a.created_at,
        )
        for a in rows
    ]


@router.get("/{session_id}", response_model=ReportResponse)
async def get_report(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the report for a completed session."""
    from fastapi import HTTPException  # noqa: PLC0415

    from app.models.report import Report  # noqa: PLC0415
    from app.models.session import InterviewSession  # noqa: PLC0415

    # Verify session ownership
    session_result = await db.execute(
        select(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.user_id == current_user.user_id,
        )
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    report_result = await db.execute(
        select(Report).where(Report.session_id == session_id)
    )
    report = report_result.scalar_one_or_none()

    if not report:
        raise HTTPException(
            status_code=404,
            detail="Report not found. Use POST /reports/{session_id}/generate to create one.",
        )

    return _build_report_response(report)


@router.post(
    "/{session_id}/generate",
    response_model=ReportResponse,
    # 200, not 201: this is idempotent and returns an existing report unchanged
    # as often as it creates a new one.
    status_code=status.HTTP_200_OK,
)
async def generate_report(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    emitter: EventEmitter = Depends(get_event_emitter),
):
    """
    Generate the AI performance report for a completed session.

    Calls the GLM report_generator prompt with the full session transcript
    (every question, answer, and score) and validates the structured response
    via the same PromptBuilder -> ResponseParser -> Pydantic pipeline used for
    live answer evaluation. Falls back to a heuristic (score-averaging only,
    no AI-generated summary) if the AI evaluation cannot be produced after
    retrying -- surfaced honestly via raw_report.generated_by, never disguised
    as a full AI report.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.models.company import Company, InterviewTrack  # noqa: PLC0415
    from app.models.question import Question, Topic  # noqa: PLC0415
    from app.models.report import Report  # noqa: PLC0415
    from app.models.session import Answer, InterviewSession  # noqa: PLC0415
    from app.models.user import Profile  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import (  # noqa: PLC0415
        QuestionAnalysisItem,
        ReportAnalysisResponse,
        ReportGeneratorResponse,
        ReportSummaryResponse,
    )
    from app.services.report.composer import (  # noqa: PLC0415
        SUMMARY_TOKENS,
        Batch,
        batch_token_budget,
        derive_summary,
        merge,
        plan_batches,
    )

    # Verify session
    session_result = await db.execute(
        select(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.user_id == current_user.user_id,
        )
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in ("completed", "active"):
        raise HTTPException(status_code=409, detail="Session must be completed before generating report")

    # Idempotent: if the report already exists, return it rather than erroring.
    #
    # This makes the endpoint "ensure a report exists and give it to me", which
    # lets the client reach a report in ONE call. Probing with a GET first meant
    # the normal path — no report yet — logged a 404 in the browser console on
    # every first view, and a 404 cannot be suppressed from JavaScript because
    # the browser records it at the network layer. Returning early here also
    # makes concurrent requests and client retries safe: no duplicate row, and
    # no second billed generation.
    existing = await db.execute(
        select(Report).where(Report.session_id == session_id)
    )
    existing_report = existing.scalar_one_or_none()

    # A previously-saved UNSCORED report is not a result — it is a placeholder
    # written because the AI was unavailable at the time, and its own text tells
    # the candidate to retry. Returning it forever would make that instruction a
    # lie and permanently trap the session on an empty report. So only a real
    # scored report short-circuits; a placeholder is retried and upgraded in place.
    unscored_attempts = 0
    if existing_report:
        regenerate, unscored_attempts = should_regenerate(existing_report.raw_report)
        if not regenerate:
            # Either a real scored report, or a placeholder that has used up its
            # retries. Served straight from the database — no model call, no cost.
            logger.info(
                "report_served_from_database",
                session_id=str(session_id),
                unscored_attempts=unscored_attempts,
            )
            return _build_report_response(existing_report)

        logger.info(
            "regenerating_unscored_report",
            session_id=str(session_id),
            attempt=unscored_attempts + 1,
            max_attempts=_MAX_UNSCORED_ATTEMPTS,
        )

    # Load full transcript: question + answer per turn. Scoring is deferred to
    # this report step, so there are no per-answer Score rows -- the AI scores
    # each answer here from the question, expected concepts and the answer text.
    transcript_result = await db.execute(
        select(Answer, Question, Topic.name.label("topic_name"))
        .join(Question, Answer.question_id == Question.id)
        .join(Topic, Question.topic_id == Topic.id)
        .where(Answer.session_id == session_id)
        .order_by(Answer.created_at)
    )
    transcript_rows = transcript_result.all()

    if not transcript_rows:
        raise HTTPException(
            status_code=409,
            detail="No answered questions found for this session -- nothing to report on.",
        )

    track = await db.get(InterviewTrack, session.track_id)
    company = await db.get(Company, track.company_id) if track else None
    profile_result = await db.execute(select(Profile).where(Profile.user_id == current_user.user_id))
    profile = profile_result.scalar_one_or_none()
    candidate_name = (profile.full_name if profile and profile.full_name else "the candidate")

    duration_minutes = 0
    if session.started_at and session.completed_at:
        duration_minutes = max(1, int((session.completed_at - session.started_at).total_seconds() // 60))

    prompt_builder = PromptBuilder(get_prompt_loader())

    transcript_lines = []
    for ans, question, topic_name in transcript_rows:
        expected = ", ".join(question.expected_keywords or []) or "(none provided)"
        ideal = (question.ideal_answer or "").strip() or "(not provided)"
        answer_text = (ans.content or "").strip() or "(no answer given)"
        transcript_lines.append(
            f"[{topic_name}] Question: {question.content}\n"
            f"Answer: {answer_text}\n"
            f"Expected concepts: {expected}\n"
            f"Ideal answer note: {ideal}\n"
            f"question_id: {ans.question_id}"
        )
    #: The joined transcript, for the summary call — which needs the whole interview.
    user_content = _TRANSCRIPT_SEPARATOR.join(transcript_lines)
    #: The question ids, in the order asked, so concurrently-returned analyses can be put
    #: back into interview order. See services/report/composer.order_by_transcript.
    question_ids = [str(ans.question_id) for ans, _q, _t in transcript_rows]

    # Delivery metrics accumulated across the interview (pauses, fillers, pace).
    delivery = (session.session_metadata or {}).get("delivery") or {}
    delivery_words = int(delivery.get("words") or 0)
    delivery_secs = int(delivery.get("speaking_seconds") or 0)
    delivery_wpm = round((delivery_words / delivery_secs) * 60) if delivery_secs else 0
    # Unprofessional language is stated separately and last, so the model cannot
    # average it into the delivery figures. A filler count is a habit to coach; this
    # is one event a real panel writes down, and the two need different advice.
    sworn = [str(w) for w in (delivery.get("unprofessional_words") or [])] if delivery else []
    conduct = (
        " The candidate used unprofessional language during the interview: "
        + ", ".join(f'"{w}"' for w in sworn[:10])
        + ". Address this directly and briefly in the summary — in a real panel it"
        " would be noted and would weigh against them — and reflect it in the"
        " communication score. Do not moralise and do not let it dominate the report."
        if sworn
        else ""
    )
    delivery_summary = (
        f"Filler words: {int(delivery.get('filler_count') or 0)}; "
        f"pauses: {int(delivery.get('pause_count') or 0)} "
        f"(~{int(delivery.get('total_pause_seconds') or 0)}s total); "
        f"speaking pace: ~{delivery_wpm} wpm." + conduct
        if delivery
        else "No delivery metrics were captured for this session."
    )

    # ── What the candidate CLAIMED, and where they gave up ──────────────────────────────
    #
    # Both of these exist to stop a feature being gameable, and both are inert unless the
    # report actually reads them — a fairness guard the grader never sees is decoration.
    #
    # THE SELF-RATING. The candidate is asked to rate their own Java out of ten and that
    # moves the questions they get. If the score were then computed identically regardless,
    # claiming 2/10 every time would be the optimal play. Naming the claim here is what
    # closes that: clearing a foundation set after saying 3 is a different achievement from
    # clearing it after saying 9, and the grader is told to treat it as one.
    #
    # THE PIVOTS. Saying "I don't know" moves the panel to another topic. Recording how often
    # that happened is what stops it being a free instruction to serve easier questions.
    # Deliberately framed as context, not as a penalty — the declined question is already
    # scored as unanswered, and docking again would punish the same event twice. Punishing
    # honesty over bluffing would also be precisely backwards in a product built to detect
    # bluffing.
    meta = session.session_metadata or {}
    rating = meta.get("self_rating") or {}
    claimed = rating.get("rating")
    subject = str(rating.get("subject") or "").strip()
    if isinstance(claimed, int):
        strengths = ", ".join(str(x) for x in (rating.get("strengths") or [])[:8])
        self_assessment = (
            "Before the questions the candidate rated their own "
            + (subject or "ability for this role")
            + f" {claimed}/10"
            + (f" and named these as their strongest areas: {strengths}." if strengths else ".")
            + " Judge their answers AGAINST THAT CLAIM. A candidate who claimed 8 or more and"
            " could not answer straightforward questions has misjudged themselves, and saying"
            " so plainly is more useful to them than a polite score. A candidate who claimed"
            " low and answered well should be told they underrate themselves. Do not simply"
            " reward or punish the number — it is context for the gap between what they"
            " believe and what they showed."
        )
    else:
        self_assessment = "The candidate was not asked to rate themselves in this session."

    pivots = meta.get("pivots") or []
    if pivots:
        offered = ", ".join(str(p.get("offered") or "?") for p in pivots[:8])
        pivot_note = (
            f"The candidate said they did not know the topic on {len(pivots)} occasion(s), and"
            f" the panel moved them to another area ({offered}). Note this in the topic"
            " breakdown as ground they could not engage with. Do NOT add a separate penalty"
            " for it — those questions already count as unanswered, and admitting a gap"
            " honestly is better behaviour than bluffing, which this report scores"
            " separately."
        )
    else:
        pivot_note = ""

    # Previous completed report for this candidate, for a progress comparison.
    prev = await db.scalar(
        select(Report)
        .where(Report.user_id == current_user.user_id, Report.session_id != session_id)
        .order_by(Report.created_at.desc())
        .limit(1)
    )
    if prev:
        previous_performance = (
            f"Their previous interview scored {prev.overall_score}/100 "
            f"(readiness: {prev.readiness_level}). Compare this interview to it and note "
            "whether they improved or regressed, and encourage them accordingly."
        )
    else:
        previous_performance = "This is their first interview — welcome them warmly and set a baseline."

    # THE SESSION BRIEF, IN THE USER MESSAGE — WHICH IS WHAT MAKES THE RUBRIC CACHEABLE.
    #
    # Everything here used to be interpolated into report_generator.md as $placeholders. That
    # made the system block different on every single report, so the provider could never
    # cache it: 2,778 tokens of static rubric re-sent and re-billed at full price on the most
    # expensive call in the product.
    #
    # Moving the varying parts down here leaves the rubric byte-identical, so it is written
    # to the provider cache once and read at a tenth of the price after — worth ~$0.0075 a
    # report, about 4.5% of a warm interview. Exactly the change that took the GD round down
    # 59%; see docs/AI-COST-MODEL.md.
    #
    # It also scales the right way. A provider cache entry lives ~5 minutes and every read
    # refreshes it, so the hit rate is a function of how often reports are generated — it is
    # near zero for one user a day and near 100% once reports are minutes apart. This is one
    # of the few savings that literally arrives as the product gets busier.
    session_brief = "\n".join(
        [
            "## This session",
            "",
            f"Candidate: {candidate_name}",
            f"Company: {company.name if company else 'Unknown Company'}",
            f"Track: {track.name if track else 'Unknown Track'}",
            f"Questions asked: {len(transcript_rows)}",
            f"Duration: {duration_minutes} minutes",
            "",
            "### Delivery (how they spoke)",
            delivery_summary,
            "",
            "### Progress vs their last interview",
            previous_performance,
            "",
            self_assessment,
            *((["", pivot_note]) if pivot_note else []),
            "",
            "---",
            "",
        ]
    )

    summary_messages = prompt_builder.chat_static(
        system_template="report_summary",
        user_content=session_brief + user_content,
    )

    # Tries primary then fallback provider; if all fail we degrade to a
    # heuristic score-only report below rather than 503-ing the candidate.
    # Shared blocks surfaced in the report so the UI can show delivery analysis
    # (pauses/fillers) and a comparison to the candidate's previous interview.
    delivery_block = {**delivery, "wpm": delivery_wpm} if delivery else None
    previous_block = (
        {
            "overall_score": prev.overall_score,
            "readiness_level": prev.readiness_level,
            "created_at": prev.created_at.isoformat() if prev.created_at else None,
        }
        if prev
        else None
    )

    # RATE LIMIT HERE, not as a route dependency — and this is the fix for the 429s.
    #
    # As a dependency it ran before the handler, so it counted EVERY call, including the
    # ones that just hand back a report already in the database. But the client's read path
    # IS this endpoint: useReport POSTs to /generate because generation is idempotent, so
    # opening a finished report, coming back to the tab after staleTime, or tapping
    # "Generate again" each spent one of six per hour. A candidate re-reading their own
    # finished report six times was locked out of the thing the limit was supposed to
    # protect.
    #
    # The limit exists to stop repeated EXPENSIVE AI CALLS, so it belongs at the point one
    # is about to be made. Everything above this line — an existing scored report, a
    # placeholder out of retries — has already returned, free and unmetered.
    #
    # ONE UNIT FOR THE WHOLE REPORT, not one per part. The report is now several concurrent
    # model calls, and counting each of them would divide the candidate's hourly allowance by
    # the length of their interview — a 19-question interview would spend four units to
    # produce one report, and a longer one would spend more. The limit protects against
    # repeated REPORTS, so it counts reports.
    await enforce_limit(
        get_redis(),
        key=CacheKeys.rate_limit_report(str(current_user.user_id)),
        limit=settings.RATE_LIMIT_REPORT_PER_HOUR,
        window_seconds=3600,
        action="generating a report",
    )

    ai_report: ReportGeneratorResponse | None = None
    #: Set by whichever except branch runs. Defaults to the generic provider reason so
    #: the field is never absent from a stored unscored report.
    unscored_reason = _REASON_PROVIDER
    last_raw_content = ""
    #: True when the summary call failed and the whole-interview view was derived from the
    #: per-question scores instead. Stored, so a partial report is never presented as a full
    #: one — see composer.derive_summary.
    derived_summary = False
    _ai_started = perf_counter()

    # RELEASE THE DATABASE CONNECTION BEFORE THE MODEL CALL.
    #
    # This is the change that decides whether a campus drive takes the site down, and it
    # is worth being precise about why. The AI call is awaited, so it does NOT block the
    # event loop — uvicorn happily serves other requests during those twenty seconds.
    # What it DID hold is a pooled Postgres connection, because Depends(get_db) opens the
    # session when the request starts and closes it when the response returns.
    #
    # The pool is DB_POOL_SIZE + DB_MAX_OVERFLOW = 30 per process. A report holds one
    # connection for ~21s, so a sustained ~1.4 reports a second exhausts it — and once
    # exhausted, EVERY other endpoint blocks for up to DB_POOL_TIMEOUT (30s) waiting for
    # a connection. A thousand candidates finishing interviews in the same ten minutes,
    # which is exactly what a drive looks like, is several times that rate. The symptom
    # would not be "reports are slow", it would be the whole API timing out.
    #
    # Committing here returns the connection to the pool. The reads above are already
    # done and the session factory sets expire_on_commit=False, so every object loaded
    # so far stays usable; the write below re-acquires a connection lazily. Net effect:
    # a report occupies a connection for milliseconds at each end instead of for the
    # whole generation.
    await db.commit()

    try:
        # ── ONE REPORT, SEVERAL CONCURRENT CALLS ──────────────────────────────────────────
        #
        # HARD time budget. Managed hosts (Render included) cut the request at their gateway
        # after ~100s and return a 502 that carries no CORS headers — which reaches the
        # browser as an opaque CORS error instead of a real failure. So the whole thing must
        # be capped well inside that window and degrade rather than be killed.
        #
        # AND THE SHAPE OF THE WORK IS WHAT CHANGED, not the cap. A report used to be ONE
        # call whose response carried the summary AND one analysis entry per question, so its
        # output — and therefore its latency, which is output-token-bound on these providers —
        # grew with the interview. A 13-answer report measured 34s locally and ran past the
        # budget in production: the candidate saw "Scoring took too long" and a 0/100 for an
        # interview that was entirely gradeable, and every retry hit the same wall because a
        # retry of one big call is still one big call.
        #
        # It is now a summary call plus one batch per six questions, ALL IN FLIGHT AT ONCE.
        # The wall clock is the slowest single part instead of the sum of all of them, and a
        # part that fails costs only its own questions — `_report_is_complete` accepts
        # two-thirds coverage, so the report still scores. See services/report/composer.py.
        #
        # The semaphore still bounds how many reports generate at once per process, so a
        # cohort finishing together queues cheaply here rather than on the database pool or
        # at the provider. Queue time counts against the same budget as generating,
        # deliberately: a candidate queued for 50 seconds is better served the honest
        # placeholder with a retry than a request that hangs past the gateway.
        batches = plan_batches(len(transcript_rows))

        async def _one_batch(batch: Batch) -> ReportAnalysisResponse:
            """Grade one slice of the interview. Only this slice is lost if it fails."""
            slice_lines = transcript_lines[batch.start : batch.end]
            return (
                await generate_structured(
                    ReportAnalysisResponse,
                    prompt_builder.chat_static(
                        system_template="report_analysis",
                        user_content=(
                            f"Grade these {len(slice_lines)} answers. Return exactly "
                            f"{len(slice_lines)} entries in `question_analysis`, in this "
                            "order, copying each `question_id` exactly.\n\n"
                            + _TRANSCRIPT_SEPARATOR.join(slice_lines)
                        ),
                    ),
                    max_tokens=batch_token_budget(len(slice_lines)),
                    attempts_per_provider=2,
                    cost_tier=CostTier.BALANCED,
                    # One entry per question in the slice, or the batch is a failure and its
                    # questions fall to the other batches' coverage. A batch that returns two
                    # entries for six questions is the truncation this split exists to avoid,
                    # and accepting it would put a report on screen missing most of its
                    # breakdown.
                    is_valid=lambda r: len(r.question_analysis) >= max(1, len(slice_lines) - 1),
                    cache_system=True,
                    context="report_analysis",
                )
            )[0]

        async def _summary() -> tuple[ReportSummaryResponse, str]:
            """The whole-interview view. Derived from the batches if this fails."""
            return await generate_structured(
                ReportSummaryResponse,
                summary_messages,
                # Does NOT scale with the interview any more, which is the point: the summary
                # of a 20-answer interview is the same three-to-four sentences as a 6-answer
                # one, and the roadmap is capped at three items by the prompt.
                max_tokens=SUMMARY_TOKENS,
                # TWO ATTEMPTS PER PROVIDER, INSIDE THE SAME WALL-CLOCK BOUND.
                #
                # A 400, a 429 or a refused key comes back in a second or two, and with one
                # attempt each the rest of the budget was then spent doing nothing while the
                # candidate was told the model was unreachable. The deadline below bounds the
                # total, so this cannot make the request longer — it only decides how many
                # chances fit inside a fixed window.
                #
                # The fallback provider is deliberately KEPT in the chain. It is worth the
                # least when the primary is merely slow and the most when the primary refuses
                # outright — which is exactly what the daily spend cap does, instantly and for
                # the rest of the UTC day.
                attempts_per_provider=2,
                # BALANCED, not DEEP: DEEP buys adaptive reasoning, which bills as output and
                # roughly doubled the cost of the most expensive call in the app. The rubric
                # is already explicit in the prompt.
                cost_tier=CostTier.BALANCED,
                # Reject a summary with no competency bars. Both `dimension_scores` and the
                # roadmap are optional in the schema, so when the model economised it dropped
                # them and the report saved with a blank panel.
                is_valid=lambda r: all(k in (r.dimension_scores or {}) for k in _REQUIRED_DIMENSIONS),
                # The rubric is byte-identical on every report now that the per-session values
                # live in the user brief, so it is cached at the provider: written once at
                # 1.25x, read at 0.1x thereafter.
                cache_system=True,
                context="report_generation",
            )

        async def _generate_within_budget() -> None:
            nonlocal ai_report, last_raw_content, unscored_reason, derived_summary

            # TIMED SEPARATELY, BECAUSE "took too long" WAS NOT ACTIONABLE.
            #
            # Queueing and generating fail identically from the outside but are different
            # problems: queueing means too few slots for the number of people finishing at
            # once, generating means the interview was long or the provider was slow. One is
            # fixed by raising REPORT_CONCURRENCY and the other is not fixed by that at all.
            _queue_started = perf_counter()
            async with _report_slots:
                queue_waited = perf_counter() - _queue_started
                if queue_waited > 1.0:
                    logger.info(
                        "report_queue_wait_seconds",
                        session_id=str(session_id),
                        waited_s=round(queue_waited, 1),
                        concurrency=settings.REPORT_CONCURRENCY,
                    )

                # EVERY PART FAILS ON ITS OWN. `return_exceptions=True` is what makes the
                # split worth anything: without it one batch raising would cancel the rest
                # and lose a report that was almost entirely generated — exactly the
                # all-or-nothing behaviour being removed.
                #
                # Held as named tasks rather than passed inline so each result keeps its own
                # type, and so the `finally` below can guarantee nothing is left running: an
                # orphaned model call would keep billing after the candidate has already been
                # answered, which is the leak that `asyncio.create_task` caused in the quiz
                # path. Cancelling a gather does cancel its children, but only the tasks it
                # still owns — this makes it true regardless of where the cancellation lands.
                summary_task = asyncio.ensure_future(_summary())
                batch_tasks = [asyncio.ensure_future(_one_batch(b)) for b in batches]
                try:
                    await asyncio.gather(
                        summary_task, *batch_tasks, return_exceptions=True
                    )
                finally:
                    for task in (summary_task, *batch_tasks):
                        if not task.done():
                            task.cancel()

            analyses: list[QuestionAnalysisItem] = []
            failed_batches = 0
            for task in batch_tasks:
                error = task.exception() if not task.cancelled() else None
                if task.cancelled() or error is not None:
                    failed_batches += 1
                    logger.warning(
                        "report_analysis_batch_failed",
                        session_id=str(session_id),
                        error_type=type(error).__name__ if error else "CancelledError",
                        error=str(error)[:200] if error else "cancelled",
                    )
                    continue
                analyses.extend(task.result().question_analysis)

            summary: ReportSummaryResponse | None = None
            summary_error = (
                summary_task.exception() if not summary_task.cancelled() else TimeoutError()
            )
            if summary_error is not None:
                unscored_reason = _classify_failure(summary_error)
                logger.warning(
                    "report_summary_failed",
                    session_id=str(session_id),
                    error_type=type(summary_error).__name__,
                    error=str(summary_error)[:200],
                    analyses=len(analyses),
                )
                # ── THE LAST 0/100 ────────────────────────────────────────────────────────
                #
                # Every answer was graded and only the covering paragraph is missing.
                # Returning the unscored placeholder here would throw away a complete
                # grading of the interview because one of four calls did not land, and it
                # would tell a candidate whose answers WERE all scored that scoring failed.
                # Derived numbers all trace to a model-assigned per-question score or a
                # counted delivery metric — see composer.derive_summary.
                summary = derive_summary(
                    analyses,
                    candidate_name=candidate_name,
                    topics=sorted({topic_name for _, _, topic_name in transcript_rows}),
                    answered=len(transcript_rows),
                    delivery=delivery,
                )
                derived_summary = summary is not None
            else:
                summary, last_raw_content = summary_task.result()

            if summary is None:
                # Nothing to build on: no summary AND no graded answers. This is the only
                # remaining route to the honest placeholder.
                return

            candidate = merge(summary, analyses, question_ids)
            if not _report_is_complete(candidate, len(transcript_rows)):
                # Too little of the interview came back to be worth showing. Deliberately not
                # stored: a report missing most of its breakdown looks finished and is not.
                logger.warning(
                    "report_parts_insufficient",
                    session_id=str(session_id),
                    analyses=len(analyses),
                    answered=len(transcript_rows),
                    failed_batches=failed_batches,
                )
                return

            if failed_batches or derived_summary:
                logger.info(
                    "report_generated_partially",
                    session_id=str(session_id),
                    failed_batches=failed_batches,
                    total_batches=len(batches),
                    derived_summary=derived_summary,
                    analyses=len(analyses),
                    answered=len(transcript_rows),
                )
            ai_report = candidate

        # ONE timeout over the queue and every part. A part still running when it expires is
        # cancelled by the gather being cancelled — nothing is orphaned to keep billing after
        # the candidate has already been answered.
        await asyncio.wait_for(
            _generate_within_budget(),
            timeout=report_ai_budget_seconds(),
        )
    except (AIProviderUnavailableError, TimeoutError) as exc:
        unscored_reason = _classify_failure(exc)
        logger.warning(
            "ai_report_unavailable_using_heuristic",
            session_id=str(session_id),
            reason=type(exc).__name__,
            unscored_reason=unscored_reason,
            elapsed_s=round(perf_counter() - _ai_started, 1),
            # THE NUMBERS THAT MAKE THIS DIAGNOSABLE FROM ONE LINE. "Scoring took too long"
            # and "the model was unreachable" look identical from outside and need opposite
            # fixes: an elapsed time near the budget means the interview was long or the host
            # is slow; a failure after two seconds means a provider refused. Neither can be
            # told apart without the budget and the size beside the elapsed time.
            budget_s=report_ai_budget_seconds(),
            questions=len(transcript_rows),
            max_tokens=report_token_budget(len(transcript_rows)),
        )
    except Exception:
        # Deliberately broad. Anything unexpected here — a provider SDK raising
        # an unmapped error, a malformed response — must still yield a report.
        # A 500 from this endpoint reaches the browser as an opaque CORS failure
        # (the error page carries no CORS headers), which tells the candidate
        # nothing and looks like the app is broken.
        logger.exception(
            "ai_report_unexpected_error_using_heuristic",
            session_id=str(session_id),
            elapsed_s=round(perf_counter() - _ai_started, 1),
        )

    if ai_report is not None:
        # STUDY RESOURCES ARE ATTACHED HERE, NOT GENERATED ABOVE.
        #
        # The prompt tells the model to leave `resources` empty, and this overwrites it
        # regardless — an instruction is a request, this is the guarantee. Two reasons, and
        # the second is the one that compounds:
        #
        #   Trust. A book title or a docs URL is exactly the kind of specific, plausible
        #   detail a model invents, and a dead link in a study plan wastes a candidate's
        #   evening. resources.yaml is human-verified and carries a `verified:` date.
        #
        #   Cost. This is the most expensive call in the product and it is OUTPUT-bound,
        #   sitting on its token cap — so every resource object the model writes displaces
        #   something a candidate actually reads, and is paid for again on every report
        #   forever. Resources are a function of the topic, not of the candidate, so paying
        #   per candidate for them is paying repeatedly for one answer.
        #
        # Curated first, then a globally shared cache, then a small one-off generation that
        # writes back to that cache — see services/prep/study_resources.py for why the
        # shared tier is what makes cost per user FALL as the user base grows.
        roadmap = [item.model_dump() for item in ai_report.improvement_roadmap]
        try:
            # BOUNDED, and it was not. This loops over every roadmap item calling `resolve`,
            # which on a cache miss makes another AI call — so eight uncached topics meant
            # eight sequential generations AFTER the report's own 85s budget was already
            # spent. Nothing capped the total, so the client's 120s timeout arrived first and
            # the candidate saw "Report Unavailable" for a report the server was still
            # assembling. Capping the AI call alone did not fix it because this was never
            # inside that cap.
            roadmap = await asyncio.wait_for(
                attach_to_roadmap(db, roadmap),
                timeout=settings.REPORT_RESOURCE_BUDGET_SECONDS,
            )
        except (Exception, TimeoutError) as exc:  # noqa: BLE001
            # Never at the cost of the report. An item still carries its topic, score gap
            # and study-hours estimate without resources, which is most of its value; a
            # report that failed to save has none of it.
            #
            # A partial roadmap is not lost work either: `resolve` writes each topic it did
            # finish into the shared cache, so the next candidate to need that topic gets it
            # instantly. This report pays the discovery; every later one benefits.
            logger.warning(
                "roadmap_resource_attach_failed",
                session_id=str(session_id),
                error_type=type(exc).__name__,
                error=str(exc) or type(exc).__name__,
                budget_seconds=settings.REPORT_RESOURCE_BUDGET_SECONDS,
            )

        report = Report(
            session_id=session_id,
            user_id=current_user.user_id,
            overall_score=ai_report.overall_score,
            overall_score_label=_fit(Report.overall_score_label, ai_report.overall_score_label),
            executive_summary=ai_report.executive_summary,
            readiness_level=_fit(Report.readiness_level, ai_report.readiness_level),
            strengths=ai_report.strengths,
            weaknesses=ai_report.weaknesses,
            topic_scores=ai_report.topic_scores,
            improvement_roadmap=roadmap,
            raw_report={
                "generated_by": "ai",
                "strategy": _GENERATION_STRATEGY,
                # True when the summary call failed and the whole-interview view was
                # calculated from the per-question scores instead. Recorded so a partial
                # report is never mistaken for a fully generated one in the logs or in a
                # later investigation — the candidate's report is complete and scored either
                # way, but these two were not produced the same way.
                "summary_derived": derived_summary,
                "readiness_reasoning": ai_report.readiness_reasoning,
                "dimension_scores": ai_report.dimension_scores,
                "performance_percentile": ai_report.performance_percentile,
                "question_analysis": [item.model_dump() for item in ai_report.question_analysis],
                "delivery": delivery_block,
                "previous": previous_block,
                "raw_response": last_raw_content,
            },
        )
    else:
        # AI evaluation unavailable after retrying -- fall back to a heuristic
        # score-averaging report rather than blocking the candidate entirely,
        # but mark it plainly as heuristic (never disguised as a full AI report).
        logger.error(
            "ai_report_generation_failed_using_heuristic_fallback",
            session_id=str(session_id),
        )
        # Scoring is AI-only (deferred to this step), so without the AI we
        # cannot produce real scores. Emit an honest "pending" report with the
        # topics attempted, marked plainly as unscored, rather than inventing
        # numbers -- the candidate can retry generation shortly.
        topics_attempted = sorted({topic_name for _, _, topic_name in transcript_rows})
        report = Report(
            session_id=session_id,
            user_id=current_user.user_id,
            overall_score=0.0,
            overall_score_label="Pending",
            executive_summary=(
                f"{candidate_name} completed {len(transcript_rows)} questions covering "
                f"{', '.join(topics_attempted) or 'several topics'}. AI scoring is temporarily "
                "unavailable, so this report has not been scored yet -- please retry report "
                "generation shortly to get full feedback."
            ),
            readiness_level="needs_more_practice",
            strengths=[],
            weaknesses=[],
            topic_scores={},
            improvement_roadmap=[],
            raw_report={
                "generated_by": _UNSCORED,
                # WHICH STRATEGY FAILED. Stamped on failure as well as success, which is what
                # keeps the rescue above from looping: this row has now had its chance under
                # the current code, so it falls back to the ordinary cap and cooldown.
                "strategy": _GENERATION_STRATEGY,
                # WHY it is unscored, so the candidate is told the truth instead of one
                # generic "temporarily unavailable" for four different situations. A
                # candidate who has used their day's practice needs to hear something
                # completely different from one hitting a provider outage, and before
                # this both produced the same sentence.
                "unscored_reason": unscored_reason,
                # Counts toward _MAX_UNSCORED_ATTEMPTS so repeated page views
                # cannot keep paying for a model that is failing.
                "unscored_attempts": unscored_attempts + 1,
                # WHEN, not just how many. The cooldown in `should_regenerate` is measured
                # from this; without it an exhausted report can never be aged and stays
                # permanently pending, which is the bug that field exists to fix.
                "unscored_last_at": datetime.now(UTC).isoformat(),
                "topics_attempted": topics_attempted,
                "delivery": delivery_block,
                "previous": previous_block,
            },
        )

    if existing_report is not None:
        # Upgrade the placeholder row in place rather than inserting — session_id
        # is unique, so a second row is impossible anyway.
        for field, value in {
            "overall_score": report.overall_score,
            "overall_score_label": report.overall_score_label,
            "executive_summary": report.executive_summary,
            "readiness_level": report.readiness_level,
            "strengths": report.strengths,
            "weaknesses": report.weaknesses,
            "topic_scores": report.topic_scores,
            "improvement_roadmap": report.improvement_roadmap,
            "raw_report": report.raw_report,
        }.items():
            setattr(existing_report, field, value)
        report = existing_report
    else:
        db.add(report)
    # Rate the round BEFORE committing, so the ledger row and the report land in one
    # transaction — a report the candidate can see with no rating attached is the one
    # state that would make the number look broken.
    #
    # Only a scored report counts. The heuristic fallback writes overall_score 0.0
    # with generated_by=unscored, and rating a round the model failed to score would
    # punish a candidate for our outage.
    if (report.raw_report or {}).get("generated_by") == "ai":
        topics_covered = sorted({topic_name for _, _, topic_name in transcript_rows})
        await record_round(
            db,
            user_id=current_user.user_id,
            session_id=session_id,
            kind="interview",
            tier=tier_for(
                question_count=len(transcript_rows),
                # On the TRACK, not the company — a recruiter runs tracks of
                # different difficulty, and it is the track that was sat.
                company_difficulty=track.difficulty_level if track else None,
                had_cross_questions=bool(
                    (session.session_metadata or {}).get("cross_question_ids")
                ),
            ),
            score_out_of_100=float(report.overall_score),
            topics=topics_covered,
        )

    await db.commit()
    await db.refresh(report)
    overall_score = report.overall_score

    with contextlib.suppress(Exception):
        await emitter.emit(
            ReportGeneratedEvent(
                user_id=current_user.user_id,
                session_id=session_id,
                payload=ReportGeneratedPayload(
                    report_id=report.id,
                    overall_score=overall_score,
                    generation_time_ms=100,
                    questions_evaluated=session.questions_asked or 0,
                ),
            )
        )

    logger.info(
        "report_generated",
        report_id=str(report.id),
        session_id=str(session_id),
        score=overall_score,
    )

    # Record the interview in the unified activity feed so the history surface
    # shows it alongside GD / communication / quiz activities.
    from app.services.activity import log_activity  # noqa: PLC0415

    await log_activity(
        db,
        current_user.user_id,
        activity_type="interview",
        title=(
            f"{company.name if company else 'Interview'}"
            f"{' — ' + track.name if track else ''}"
        ),
        score=overall_score,
        details={
            "session_id": str(session_id),
            "report_id": str(report.id),
            "readiness_level": report.readiness_level,
            "questions": len(transcript_rows),
        },
    )

    return _build_report_response(report)


class PublicReport(BaseModel):
    """
    A shared report as seen by someone without an account.

    A deliberately narrowed view. It carries the assessment — score, readiness,
    summary, strengths, weaknesses, topic and competency breakdowns — and omits
    everything that is not the candidate's own to publish or that a viewer has no
    business seeing: the session id, the per-question transcript, the improvement
    roadmap, and the delivery analysis of how they spoke.
    """

    report_id: uuid.UUID
    candidate_name: str
    track_name: str
    company_name: str
    overall_score: float
    overall_score_label: str
    readiness_level: str
    executive_summary: str
    strengths: list[str]
    weaknesses: list[str]
    topic_scores: dict[str, float]
    dimension_scores: dict[str, float]
    created_at: datetime


@router.get("/public/{report_id}", response_model=PublicReport)
async def get_public_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch a shared report. NO AUTHENTICATION — this is the whole point of sharing.

    Access is gated on the owner having explicitly enabled sharing, and on knowing
    the report's UUID, which is unguessable. Turning sharing off makes the link
    dead immediately, so the candidate keeps control after publishing.

    A report that is not shared returns 404, not 403: a 403 would confirm that a
    report with that id exists, which is information the caller has not earned.

    Declared BEFORE "/{session_id}" would otherwise match it — FastAPI resolves in
    declaration order, and "public" would be parsed as a session UUID and fail.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    from app.models.company import Company, InterviewTrack  # noqa: PLC0415
    from app.models.report import Report  # noqa: PLC0415
    from app.models.session import InterviewSession  # noqa: PLC0415
    from app.models.user import Profile  # noqa: PLC0415

    report = await db.scalar(select(Report).where(Report.id == report_id))
    if report is None or not report.is_shared:
        raise HTTPException(status_code=404, detail="This report is not shared, or does not exist.")

    session = await db.get(InterviewSession, report.session_id)
    track = await db.get(InterviewTrack, session.track_id) if session and session.track_id else None
    company = await db.get(Company, track.company_id) if track else None
    profile = await db.scalar(select(Profile).where(Profile.user_id == report.user_id))

    raw = report.raw_report or {}

    return PublicReport(
        report_id=report.id,
        candidate_name=(profile.full_name if profile and profile.full_name else "Candidate"),
        track_name=track.name if track else "Technical Interview",
        company_name=company.name if company else "",
        overall_score=_as_float(report.overall_score),
        overall_score_label=report.overall_score_label or "",
        readiness_level=report.readiness_level or "",
        executive_summary=report.executive_summary or "",
        strengths=_as_str_list(report.strengths),
        weaknesses=_as_str_list(report.weaknesses),
        topic_scores=_as_score_map(report.topic_scores),
        dimension_scores=_as_score_map(raw.get("dimension_scores")),
        created_at=report.created_at,
    )


@router.patch("/{report_id}/share")
async def toggle_share(
    report_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException  # noqa: PLC0415

    from app.models.report import Report  # noqa: PLC0415

    result = await db.execute(
        select(Report).where(
            Report.id == report_id,
            Report.user_id == current_user.user_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    report.is_shared = not report.is_shared
    await db.commit()

    return {"is_shared": report.is_shared, "report_id": str(report_id)}


def _fit(model_column, value: str) -> str:
    """
    Clamp a string to its database column's length.

    The model writes some of these values as free text — `overall_score_label`
    has no max_length in the response schema but lands in a VARCHAR(50). One
    over-long label makes Postgres raise StringDataRightTruncation on commit, so
    report generation 500s for that session on every retry, permanently.

    Clamping here rather than adding max_length to the response schema is
    deliberate: a validation failure would discard the whole response and pay for
    a retry, when a slightly shortened label is a perfectly good report. The limit
    is read from the column so it cannot drift out of sync with the schema.
    """
    limit = getattr(model_column.type, "length", None)
    text = (value or "").strip()
    if limit and len(text) > limit:
        logger.warning(
            "report_field_truncated",
            column=model_column.name,
            limit=limit,
            length=len(text),
        )
        return text[:limit]
    return text


def _as_float(value: object, default: float = 0.0) -> float:
    """Coerce a stored value to float, tolerating strings like "8" or "7.5"."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().split("/")[0])  # tolerates "8/10"
        except ValueError:
            return default
    return default


def _as_score_map(value: object) -> dict[str, float]:
    """Coerce a stored mapping to {str: float}, dropping unusable entries."""
    if not isinstance(value, dict):
        return {}
    return {str(k): _as_float(v) for k, v in value.items()}


def _as_dicts(value: object) -> list[dict]:
    """Keep only the dict entries of a stored list."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None]


def _build_report_response(report) -> ReportResponse:
    parsed_roadmap = []
    for item in _as_dicts(report.improvement_roadmap):
        resources = [
            ImprovementResource(
                type=r.get("type", ""),
                title=r.get("title", ""),
                url=r.get("url"),
                author=r.get("author"),
            )
            for r in _as_dicts(item.get("resources"))
        ]
        parsed_roadmap.append(
            ImprovementItem(
                priority=int(_as_float(item.get("priority"), 1)),
                topic=item.get("topic", ""),
                current_score=_as_float(item.get("current_score")),
                target_score=_as_float(item.get("target_score")),
                study_hours_estimate=int(_as_float(item.get("study_hours_estimate"))),
                resources=resources,
            )
        )

    raw = report.raw_report or {}
    question_analysis = [
        QuestionAnalysisResponseItem(
            question_id=str(qa.get("question_id", "")),
            question=qa.get("question", ""),
            answer_quality=qa.get("answer_quality", ""),
            score=_as_float(qa.get("score")),
            missing_concepts=_as_str_list(qa.get("missing_concepts")),
            ideal_answer_summary=qa.get("ideal_answer_summary", ""),
        )
        for qa in _as_dicts(raw.get("question_analysis"))
    ]


    return ReportResponse(
        id=report.id,
        session_id=report.session_id,
        overall_score=_as_float(report.overall_score),
        overall_score_label=report.overall_score_label,
        executive_summary=report.executive_summary,
        readiness_level=report.readiness_level,
        readiness_reasoning=raw.get("readiness_reasoning", ""),
        strengths=_as_str_list(report.strengths),
        weaknesses=_as_str_list(report.weaknesses),
        topic_scores=_as_score_map(report.topic_scores),
        dimension_scores=_as_score_map(raw.get("dimension_scores")),
        performance_percentile=int(_as_float(raw.get("performance_percentile"), 50)),
        question_analysis=question_analysis,
        improvement_roadmap=parsed_roadmap,
        is_shared=report.is_shared,
        created_at=report.created_at,
        pdf_url=report.pdf_url,
        delivery=raw.get("delivery") if isinstance(raw.get("delivery"), dict) else None,
        previous=raw.get("previous") if isinstance(raw.get("previous"), dict) else None,
        # Only meaningful when the report is unscored; None otherwise, so the client can
        # branch on its presence rather than comparing a label.
        unscored_reason=(
            raw.get("unscored_reason") if raw.get("generated_by") == _UNSCORED else None
        ),
    )
