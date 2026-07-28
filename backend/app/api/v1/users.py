"""
User Endpoints — api/v1/users.py

GET    /api/v1/users/me/profile          — Get current user's extended profile
PATCH  /api/v1/users/me/profile          — Update profile
GET    /api/v1/users/me/stats            — Get interview statistics
GET    /api/v1/users/me/sessions         — Get session history (paginated)
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.security import CurrentUser
from app.db.session import AsyncSession, get_db
from app.models.session import InterviewSession
from app.models.user import Profile

logger = structlog.get_logger(__name__)
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    bio: str | None = None
    target_company: str | None = None
    experience_years: int | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    #: Profile picture. Editable so the field the profile page shows actually
    #: persists; it was previously read-only, so any value the UI sent was
    #: silently dropped.
    avatar_url: str | None = None
    timezone: str | None = None


class ProfileResponse(BaseModel):
    user_id: uuid.UUID
    full_name: str | None
    avatar_url: str | None
    bio: str | None
    target_company: str | None
    experience_years: int | None
    linkedin_url: str | None
    github_url: str | None
    timezone: str
    updated_at: datetime


class UserStatsResponse(BaseModel):
    total_sessions: int
    completed_sessions: int
    average_score: float | None
    total_questions_answered: int
    hours_practiced: float
    best_score: float | None
    streak_days: int


class SessionSummaryResponse(BaseModel):
    id: uuid.UUID
    track_name: str
    company_name: str
    program: str | None = None
    topics: list[str] = []
    status: str
    mode: str
    questions_asked: int
    overall_score: float | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: int | None


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/me/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Profile).where(Profile.user_id == current_user.user_id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        from fastapi import HTTPException  # noqa
        raise HTTPException(status_code=404, detail="Profile not found")

    return ProfileResponse(
        user_id=profile.user_id,
        full_name=profile.full_name,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        target_company=profile.target_company,
        experience_years=profile.experience_years,
        linkedin_url=profile.linkedin_url,
        github_url=profile.github_url,
        timezone=profile.timezone,
        updated_at=profile.updated_at,
    )


@router.patch("/me/profile", response_model=ProfileResponse)
async def update_profile(
    body: UpdateProfileRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Profile).where(Profile.user_id == current_user.user_id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        from fastapi import HTTPException  # noqa
        raise HTTPException(status_code=404, detail="Profile not found")

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)

    logger.info("profile_updated", user_id=str(current_user.user_id))

    return ProfileResponse(
        user_id=profile.user_id,
        full_name=profile.full_name,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        target_company=profile.target_company,
        experience_years=profile.experience_years,
        linkedin_url=profile.linkedin_url,
        github_url=profile.github_url,
        timezone=profile.timezone,
        updated_at=profile.updated_at,
    )


@router.get("/me/stats", response_model=UserStatsResponse)
async def get_stats(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Aggregate interview performance statistics for the current user."""
    from sqlalchemy import case  # noqa: PLC0415

    from app.models.report import Report  # noqa: PLC0415
    from app.models.session import Answer  # noqa: PLC0415

    # Session counts
    sessions_result = await db.execute(
        select(
            func.count(InterviewSession.id).label("total"),
            func.count(
                case((InterviewSession.status == "completed", InterviewSession.id))
            ).label("completed"),
            func.sum(
                case((InterviewSession.duration_seconds.isnot(None), InterviewSession.duration_seconds), else_=0)
            ).label("total_seconds"),
        ).where(InterviewSession.user_id == current_user.user_id)
    )
    session_row = sessions_result.one()

    # Questions answered comes from Answer rows, NOT Score rows. Per-answer
    # scoring was moved to report generation, so no Score row is ever written
    # any more — counting them made analytics permanently report zero.
    answers_result = await db.execute(
        select(func.count(Answer.id))
        .join(InterviewSession, Answer.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == current_user.user_id)
    )
    total_answers = answers_result.scalar() or 0

    # Scores now live on the generated Report (0-100), which the UI shows on a
    # 0-100 scale, so no rescaling here.
    reports_result = await db.execute(
        select(
            func.avg(Report.overall_score).label("avg_score"),
            func.max(Report.overall_score).label("best_score"),
        )
        .join(InterviewSession, Report.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == current_user.user_id)
    )
    score_row = reports_result.one()

    total_seconds = session_row.total_seconds or 0
    hours = round(total_seconds / 3600, 1)

    return UserStatsResponse(
        total_sessions=session_row.total or 0,
        completed_sessions=session_row.completed or 0,
        average_score=round(score_row.avg_score, 2) if score_row.avg_score else None,
        total_questions_answered=total_answers,
        hours_practiced=hours,
        best_score=round(score_row.best_score, 2) if score_row.best_score else None,
        streak_days=0,  # Phase 9: implement streak calculation
    )


@router.get("/me/sessions", response_model=list[SessionSummaryResponse])
async def get_session_history(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=10, le=50),
    offset: int = Query(default=0, ge=0),
):
    from app.models.company import Company, InterviewTrack  # noqa: PLC0415
    from app.models.report import Report  # noqa: PLC0415

    result = await db.execute(
        select(
            InterviewSession,
            InterviewTrack.name.label("track_name"),
            Company.name.label("company_name"),
            Report.overall_score.label("overall_score"),
        )
        .join(InterviewTrack, InterviewSession.track_id == InterviewTrack.id)
        .join(Company, InterviewTrack.company_id == Company.id)
        .outerjoin(Report, Report.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == current_user.user_id)
        # Hide empty, abandoned plan sessions (created but never answered) so the
        # history shows real interviews only, not clutter.
        .where(
            (InterviewSession.questions_asked > 0)
            | (InterviewSession.status == "completed")
        )
        .order_by(InterviewSession.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = result.all()

    summaries: list[SessionSummaryResponse] = []
    for row in rows:
        # Prefer the company/program the candidate actually chose in setup
        # (stored on the session) over the generic track name, so each interview
        # is named for what it really was.
        meta = row.InterviewSession.session_metadata or {}
        meta_company = (meta.get("company") or "").strip()
        meta_program = (meta.get("program") or "").strip()
        topics = meta.get("topics") or []
        summaries.append(
            SessionSummaryResponse(
                id=row.InterviewSession.id,
                track_name=meta_program or row.track_name,
                company_name=meta_company or row.company_name,
                program=meta_program or None,
                topics=topics if isinstance(topics, list) else [],
                status=row.InterviewSession.status,
                mode=row.InterviewSession.mode,
                questions_asked=row.InterviewSession.questions_asked,
                overall_score=row.overall_score,
                started_at=row.InterviewSession.started_at,
                completed_at=row.InterviewSession.completed_at,
                duration_seconds=row.InterviewSession.duration_seconds,
            )
        )
    return summaries
