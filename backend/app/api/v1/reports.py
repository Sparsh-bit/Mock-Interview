"""
Report Endpoints — api/v1/reports.py

GET    /api/v1/reports/{session_id}           — Get or generate report for session
POST   /api/v1/reports/{session_id}/generate  — Trigger AI report generation
GET    /api/v1/reports/{report_id}/export/pdf — Download PDF export
PATCH  /api/v1/reports/{report_id}/share      — Toggle report sharing
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime

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


# ─── Endpoints ────────────────────────────────────────────────────────────────


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
    status_code=status.HTTP_201_CREATED,
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

    from app.models.company import Company, InterviewTrack  # noqa: PLC0415
    from app.models.question import Question, Topic  # noqa: PLC0415
    from app.models.report import Report  # noqa: PLC0415
    from app.models.session import Answer, InterviewSession, Score  # noqa: PLC0415
    from app.models.user import Profile  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import ProviderError, ProviderRequest  # noqa: PLC0415
    from app.services.ai.json_validator import AIValidationError, JSONValidator  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.provider_factory import get_ai_provider  # noqa: PLC0415
    from app.services.ai.response_parser import ResponseParser  # noqa: PLC0415
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

    # Check if report already exists
    existing = await db.execute(
        select(Report).where(Report.session_id == session_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Report already exists for this session")

    # Load full transcript: question + answer + score per turn
    transcript_result = await db.execute(
        select(Answer, Question, Score, Topic.name.label("topic_name"))
        .join(Question, Answer.question_id == Question.id)
        .join(Score, Score.answer_id == Answer.id)
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
    response_parser = ResponseParser(JSONValidator())
    ai = get_ai_provider()

    transcript_lines = []
    for ans, question, score, topic_name in transcript_rows:
        transcript_lines.append(
            f"[{topic_name}] Question: {question.content}\n"
            f"Answer: {ans.content}\n"
            f"Scores -- technical: {score.technical_score}, communication: {score.communication_score}, "
            f"completeness: {score.completeness_score}, overall: {score.overall_score}\n"
            f"Feedback given at the time: {score.feedback}\n"
            f"question_id: {ans.question_id}"
        )
    user_content = "\n\n---\n\n".join(transcript_lines)

    messages = prompt_builder.chat(
        system_template="report_generator",
        user_content=user_content,
        track_name=track.name if track else "Unknown Track",
        company_name=company.name if company else "Unknown Company",
        candidate_name=candidate_name,
        total_questions=str(len(transcript_rows)),
        session_duration_minutes=str(duration_minutes),
    )

    ai_report: ReportGeneratorResponse | None = None
    last_raw_content = ""
    for attempt in range(2):
        try:
            ai_resp = await ai.complete(
                ProviderRequest(messages=messages, json_mode=True, max_tokens=3000)
            )
        except ProviderError:
            logger.warning("ai_report_provider_error", session_id=str(session_id), attempt=attempt)
            continue

        last_raw_content = ai_resp.content
        try:
            ai_report = response_parser.parse(ai_resp.content, ReportGeneratorResponse)
            break
        except AIValidationError:
            logger.warning("ai_report_validation_failed", session_id=str(session_id), attempt=attempt)
            continue

    if ai_report is not None:
        report = Report(
            session_id=session_id,
            user_id=current_user.user_id,
            overall_score=ai_report.overall_score,
            overall_score_label=ai_report.overall_score_label,
            executive_summary=ai_report.executive_summary,
            readiness_level=ai_report.readiness_level,
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
        topic_map: dict[str, list[float]] = {}
        for _, _, score, topic_name in transcript_rows:
            topic_map.setdefault(topic_name, []).append(score.overall_score)
        topic_scores = {
            topic: round(sum(scores) / len(scores) * 10, 1) for topic, scores in topic_map.items()
        }
        overall_score = round(
            sum(s.overall_score for _, _, s, _ in transcript_rows) / len(transcript_rows) * 10, 1
        )
        report = Report(
            session_id=session_id,
            user_id=current_user.user_id,
            overall_score=overall_score,
            overall_score_label="Needs Review",
            executive_summary=(
                f"{candidate_name} completed {len(transcript_rows)} questions with an average score of "
                f"{overall_score}/100. AI-generated narrative feedback is temporarily unavailable -- "
                "this is a score-only summary; please retry report generation shortly."
            ),
            readiness_level="needs_more_practice",
            strengths=[],
            weaknesses=[],
            topic_scores=topic_scores,
            improvement_roadmap=[],
            raw_report={"generated_by": "heuristic_fallback", "topic_scores": topic_scores},
        )

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


def _build_report_response(report) -> ReportResponse:
    roadmap = report.improvement_roadmap or []
    parsed_roadmap = []
    for item in roadmap:
        resources = [
            ImprovementResource(
                type=r.get("type", ""),
                title=r.get("title", ""),
                url=r.get("url"),
                author=r.get("author"),
            )
            for r in item.get("resources", [])
        ]
        parsed_roadmap.append(
            ImprovementItem(
                priority=item.get("priority", 1),
                topic=item.get("topic", ""),
                current_score=item.get("current_score", 0),
                target_score=item.get("target_score", 0),
                study_hours_estimate=item.get("study_hours_estimate", 0),
                resources=resources,
            )
        )

    raw = report.raw_report or {}
    question_analysis = [
        QuestionAnalysisResponseItem(
            question_id=str(qa.get("question_id", "")),
            question=qa.get("question", ""),
            answer_quality=qa.get("answer_quality", ""),
            score=qa.get("score", 0),
            missing_concepts=qa.get("missing_concepts", []),
            ideal_answer_summary=qa.get("ideal_answer_summary", ""),
        )
        for qa in raw.get("question_analysis", [])
    ]

    return ReportResponse(
        id=report.id,
        session_id=report.session_id,
        overall_score=report.overall_score,
        overall_score_label=report.overall_score_label,
        executive_summary=report.executive_summary,
        readiness_level=report.readiness_level,
        readiness_reasoning=raw.get("readiness_reasoning", ""),
        strengths=report.strengths or [],
        weaknesses=report.weaknesses or [],
        topic_scores=report.topic_scores or {},
        dimension_scores=raw.get("dimension_scores", {}),
        performance_percentile=raw.get("performance_percentile", 50),
        question_analysis=question_analysis,
        improvement_roadmap=parsed_roadmap,
        is_shared=report.is_shared,
        created_at=report.created_at,
        pdf_url=report.pdf_url,
    )
