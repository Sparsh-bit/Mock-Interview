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
from datetime import datetime
from time import perf_counter

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.security import CurrentUser
from app.db.session import AsyncSession, get_db
from app.events import ReportGeneratedEvent, ReportGeneratedPayload, get_event_emitter
from app.events.emitter import EventEmitter

logger = structlog.get_logger(__name__)
router = APIRouter()

#: Wall-clock ceiling on AI report generation.
#:
#: Sized to fit the host's gateway timeout (~100s on Render) in BOTH states,
#: rather than assuming the instance is warm:
#:
#:   warm (keep-warm ping active, measured ~1.5s):  1.5 + 50 =  52s
#:   cold (ping failed / instance restarted, ~37s): 37  + 50 =  87s
#:
#: Both are inside the limit, so a missed ping degrades latency but cannot
#: produce a gateway 502 — which matters because that 502 carries no CORS headers
#: and surfaces in the browser as an opaque CORS error rather than a timeout.
#:
#: Exceeding the budget is not a failure: the handler falls back to the honest
#: unscored report, which the candidate can regenerate.
_REPORT_AI_BUDGET_SECONDS = 50.0

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
    attempts = raw.get("unscored_attempts", 0)
    attempts = attempts if isinstance(attempts, int) and attempts >= 0 else 0
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
    from app.services.ai.schemas import ReportGeneratorResponse  # noqa: PLC0415

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
    user_content = "\n\n---\n\n".join(transcript_lines)

    # Delivery metrics accumulated across the interview (pauses, fillers, pace).
    delivery = (session.session_metadata or {}).get("delivery") or {}
    delivery_words = int(delivery.get("words") or 0)
    delivery_secs = int(delivery.get("speaking_seconds") or 0)
    delivery_wpm = round((delivery_words / delivery_secs) * 60) if delivery_secs else 0
    delivery_summary = (
        f"Filler words: {int(delivery.get('filler_count') or 0)}; "
        f"pauses: {int(delivery.get('pause_count') or 0)} "
        f"(~{int(delivery.get('total_pause_seconds') or 0)}s total); "
        f"speaking pace: ~{delivery_wpm} wpm."
        if delivery
        else "No delivery metrics were captured for this session."
    )

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

    messages = prompt_builder.chat(
        system_template="report_generator",
        user_content=user_content,
        track_name=track.name if track else "Unknown Track",
        company_name=company.name if company else "Unknown Company",
        candidate_name=candidate_name,
        total_questions=str(len(transcript_rows)),
        session_duration_minutes=str(duration_minutes),
        delivery_summary=delivery_summary,
        previous_performance=previous_performance,
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

    ai_report: ReportGeneratorResponse | None = None
    last_raw_content = ""
    _ai_started = perf_counter()
    try:
        # HARD time budget. Managed hosts (Render included) cut the request at
        # their gateway after ~100s and return a 502 that carries no CORS
        # headers — which reaches the browser as an opaque CORS error instead of
        # a real failure. Report generation is the slowest AI path in the app
        # (DEEP tier buys reasoning), so it must be capped well inside that
        # window and degrade to the heuristic report rather than be killed.
        ai_report, last_raw_content = await asyncio.wait_for(
            generate_structured(
                ReportGeneratorResponse,
                messages,
                # Output is 5x the price of input and this is the largest
                # response in the app, so the ceiling is set to what a report
                # actually needs rather than left generous.
                max_tokens=2600,
                # One attempt per provider: a second full retry cannot fit in the
                # budget below, and the heuristic fallback is a better use of the
                # remaining time than a retry that gets cut off.
                attempts_per_provider=1,
                # BALANCED, not DEEP: DEEP buys adaptive reasoning, which bills
                # as output and roughly doubled the cost of the single most
                # expensive call in the app. The scoring rubric is already
                # explicit in the prompt, so it does not need to reason its way
                # to the criteria.
                cost_tier=CostTier.BALANCED,
                context="report_generation",
            ),
            timeout=_REPORT_AI_BUDGET_SECONDS,
        )
    except (AIProviderUnavailableError, TimeoutError) as exc:
        logger.warning(
            "ai_report_unavailable_using_heuristic",
            session_id=str(session_id),
            reason=type(exc).__name__,
            elapsed_s=round(perf_counter() - _ai_started, 1),
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
            improvement_roadmap=[item.model_dump() for item in ai_report.improvement_roadmap],
            raw_report={
                "generated_by": "ai",
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
                # Counts toward _MAX_UNSCORED_ATTEMPTS so repeated page views
                # cannot keep paying for a model that is failing.
                "unscored_attempts": unscored_attempts + 1,
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
    )
