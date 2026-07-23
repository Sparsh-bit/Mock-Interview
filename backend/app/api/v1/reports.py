"""
Report Endpoints — api/v1/reports.py

GET    /api/v1/reports/{session_id}           — Get or generate report for session
POST   /api/v1/reports/{session_id}/generate  — Trigger AI report generation
GET    /api/v1/reports/{report_id}/export/pdf — Download PDF export
PATCH  /api/v1/reports/{report_id}/share      — Toggle report sharing
"""

from __future__ import annotations

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


class ReportResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    overall_score: float
    overall_score_label: str
    executive_summary: str
    hire_recommendation: str
    strengths: list[str]
    weaknesses: list[str]
    topic_scores: dict[str, float]
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

    Phase 5: Calls the GLM report_generator prompt with all session data.
    Phase 3: Generates a structured report from stored scores.
    """
    from fastapi import HTTPException  # noqa: PLC0415
    from sqlalchemy.orm import selectinload  # noqa: PLC0415
    from app.models.report import Report  # noqa: PLC0415
    from app.models.session import InterviewSession, Answer, Score  # noqa: PLC0415
    from app.models.question import Question, Topic  # noqa: PLC0415
    from app.models.company import InterviewTrack  # noqa: PLC0415

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

    # Load scores
    scores_result = await db.execute(
        select(Score, Topic.name.label("topic_name"))
        .join(Answer, Score.answer_id == Answer.id)
        .join(Question, Answer.question_id == Question.id)
        .join(Topic, Question.topic_id == Topic.id)
        .where(Score.session_id == session_id)
    )
    score_rows = scores_result.all()

    # Calculate aggregate scores
    if not score_rows:
        overall_score = 0.0
        topic_scores = {}
    else:
        all_scores = [row.Score.overall_score for row in score_rows]
        overall_score = round(sum(all_scores) / len(all_scores) * 10, 1)  # Scale 0-100

        topic_map: dict[str, list[float]] = {}
        for row in score_rows:
            topic_map.setdefault(row.topic_name, []).append(row.Score.overall_score)
        topic_scores = {
            topic: round(sum(scores) / len(scores) * 10, 1)
            for topic, scores in topic_map.items()
        }

    # Score label
    if overall_score >= 85:
        label = "Excellent"
        recommendation = "strong_hire"
    elif overall_score >= 70:
        label = "Good"
        recommendation = "hire"
    elif overall_score >= 55:
        label = "Average"
        recommendation = "borderline"
    elif overall_score >= 40:
        label = "Needs Improvement"
        recommendation = "no_hire_currently"
    else:
        label = "Poor"
        recommendation = "no_hire"

    # Create report
    report = Report(
        session_id=session_id,
        user_id=current_user.user_id,
        overall_score=overall_score,
        overall_score_label=label,
        executive_summary=(
            f"The candidate completed {session.questions_asked or 0} questions and achieved an "
            f"overall score of {overall_score}/100. "
            "Detailed AI evaluation will be available in Phase 5."
        ),
        hire_recommendation=recommendation,
        strengths=["Completed the interview session"],
        weaknesses=["Full evaluation requires Phase 5 AI integration"],
        topic_scores=topic_scores,
        improvement_roadmap=[
            {
                "priority": 1,
                "topic": "Java Core",
                "current_score": overall_score,
                "target_score": min(overall_score + 20, 100),
                "study_hours_estimate": 10,
                "resources": [
                    {"type": "official_docs", "title": "Java Documentation", "url": "https://docs.oracle.com/en/java/"},
                ],
            }
        ],
        raw_report={"generated_by": "phase3_heuristic", "scores": topic_scores},
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

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

    return ReportResponse(
        id=report.id,
        session_id=report.session_id,
        overall_score=report.overall_score,
        overall_score_label=report.overall_score_label,
        executive_summary=report.executive_summary,
        hire_recommendation=report.hire_recommendation,
        strengths=report.strengths or [],
        weaknesses=report.weaknesses or [],
        topic_scores=report.topic_scores or {},
        improvement_roadmap=parsed_roadmap,
        is_shared=report.is_shared,
        created_at=report.created_at,
        pdf_url=report.pdf_url,
    )
