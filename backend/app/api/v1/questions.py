"""
Question Endpoints — api/v1/questions.py

GET /api/v1/questions/tracks                    — List all active interview tracks
GET /api/v1/questions/tracks/{track_id}         — Get track detail with categories
GET /api/v1/questions/tracks/{track_id}/topics  — Get all topics for a track
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import CurrentUser
from app.db.session import AsyncSession, get_db
from app.models.company import Company, InterviewTrack, QuestionCategory

logger = structlog.get_logger(__name__)
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None


class TopicResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    order_index: int


class CategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    order_index: int
    weight: float
    topics: list[TopicResponse] = []


class TrackListResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    difficulty_level: str
    duration_minutes: int
    #: Size of this track's question BANK (not the interview length).
    question_count: int
    #: How many questions an interview on this track actually asks. The UI must
    #: show this, not question_count, or it advertises the bank size.
    interview_question_count: int
    company: CompanyResponse


class TrackDetailResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    difficulty_level: str
    duration_minutes: int
    question_count: int
    interview_question_count: int
    company: CompanyResponse
    categories: list[CategoryResponse]


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/tracks", response_model=list[TrackListResponse])
async def list_tracks(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return all interview tracks with company info. Auto-seeds if empty."""
    result = await db.execute(
        select(InterviewTrack)
        .options(selectinload(InterviewTrack.company))
        .order_by(InterviewTrack.name)
    )
    tracks = result.scalars().all()

    if not tracks:
        # Guarantee at least one track exists
        company = await db.scalar(select(Company).where(Company.slug == "cognizant"))
        if not company:
            company = Company(
                id=uuid.uuid4(),
                name="Cognizant",
                slug="cognizant",
                description="Cognizant Digital Nurture program",
                is_active=True,
            )
            db.add(company)
            await db.flush()

        track = InterviewTrack(
            id=uuid.uuid4(),
            company_id=company.id,
            name="Digital Nurture — Java FSE",
            slug="java-fse",
            description="Java Full Stack Engineer Track",
            is_active=True,
        )
        db.add(track)
        await db.commit()
        await db.refresh(track)

        # Reload with company
        res = await db.execute(
            select(InterviewTrack)
            .options(selectinload(InterviewTrack.company))
            .where(InterviewTrack.id == track.id)
        )
        tracks = res.scalars().all()

    return [
        TrackListResponse(
            id=t.id,
            name=t.name,
            slug=t.slug,
            description=t.description,
            difficulty_level=t.difficulty_level,
            duration_minutes=t.duration_minutes,
            question_count=t.question_count,
            interview_question_count=settings.INTERVIEW_QUESTION_COUNT,
            company=CompanyResponse(
                id=t.company.id,
                name=t.company.name,
                slug=t.company.slug,
                logo_url=t.company.logo_url,
            ),
        )
        for t in tracks
    ]


@router.get("/tracks/{track_id}", response_model=TrackDetailResponse)
async def get_track(
    track_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return a specific track with all categories and topics."""
    result = await db.execute(
        select(InterviewTrack)
        .options(
            selectinload(InterviewTrack.company),
            selectinload(InterviewTrack.categories).selectinload(QuestionCategory.topics),
        )
        .where(InterviewTrack.id == track_id)
    )
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    return TrackDetailResponse(
        id=track.id,
        name=track.name,
        slug=track.slug,
        description=track.description,
        difficulty_level=track.difficulty_level,
        duration_minutes=track.duration_minutes,
        question_count=track.question_count,
        interview_question_count=settings.INTERVIEW_QUESTION_COUNT,
        company=CompanyResponse(
            id=track.company.id,
            name=track.company.name,
            slug=track.company.slug,
            logo_url=track.company.logo_url,
        ),
        categories=[
            CategoryResponse(
                id=cat.id,
                name=cat.name,
                slug=cat.slug,
                order_index=cat.order_index,
                weight=cat.weight,
                topics=[
                    TopicResponse(
                        id=t.id,
                        name=t.name,
                        slug=t.slug,
                        description=t.description,
                        order_index=t.order_index,
                    )
                    for t in sorted(cat.topics, key=lambda x: x.order_index)
                ],
            )
            for cat in sorted(track.categories, key=lambda x: x.order_index)
        ],
    )


class PracticeQuestionResponse(BaseModel):
    """A single question, for practising it on its own outside an interview."""

    id: uuid.UUID
    content: str
    question_type: str
    difficulty: str
    topic: str
    #: Keywords a strong answer should contain, already stored on the question.
    #: Shown while practising: this is not a live interview, so there is nothing
    #: to withhold.
    expected_keywords: list[str] = []
    #: The reference answer, where the question bank has one.
    ideal_answer: str | None = None
    time_limit_seconds: int | None = None


@router.get("/{question_id}", response_model=PracticeQuestionResponse)
async def get_question(
    question_id: uuid.UUID,
    current_user: CurrentUser,  # noqa: ARG001 - auth required, identity unused
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch one question by id.

    Declared after the /tracks routes so those static paths are matched first —
    FastAPI resolves in declaration order, and a leading path parameter would
    otherwise swallow them and fail UUID parsing.

    Exists for the standalone practice screen: retrying a coding question must not
    require an interview session, so the question has to be reachable on its own.
    """
    from app.models.question import Question, Topic  # noqa: PLC0415

    row = (
        await db.execute(
            select(Question, Topic.name)
            .outerjoin(Topic, Question.topic_id == Topic.id)
            .where(Question.id == question_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Question not found")

    question, topic_name = row
    return PracticeQuestionResponse(
        id=question.id,
        content=question.content,
        question_type=str(question.question_type or "conceptual"),
        difficulty=str(question.difficulty or "medium"),
        topic=topic_name or "General",
        expected_keywords=list(question.expected_keywords or []),
        ideal_answer=question.ideal_answer,
        time_limit_seconds=question.time_limit_seconds,
    )
