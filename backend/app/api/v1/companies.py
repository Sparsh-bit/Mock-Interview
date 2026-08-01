"""
Campus Recruiter Endpoints — api/v1/companies.py

GET /api/v1/companies                     — every recruiter in the catalogue
GET /api/v1/companies/{slug}              — one recruiter in full
GET /api/v1/companies/{slug}/roadmap      — a dated study plan for that recruiter

Reference data, served from YAML. No database, no AI, no per-user state — so these
are cheap, cacheable, and cannot fail because a provider is down.
"""

from __future__ import annotations

import datetime as dt

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.core.security import CurrentUser
from app.db.session import AsyncSession, get_db
from app.services.prep import Company, Roadmap, build_roadmap, get_company, load_catalogue

logger = structlog.get_logger(__name__)
router = APIRouter()

#: Cache for a day at the edge. The catalogue only changes on deploy, and a
#: student comparing companies will hit this repeatedly in one sitting.
_CACHE_CONTROL = "public, max-age=86400"


@router.get("", response_model=list[Company])
@router.get("/", response_model=list[Company], include_in_schema=False)
async def list_companies(
    response: Response,
    current_user: CurrentUser,  # noqa: ARG001 - auth required, identity unused
    tier: str | None = Query(default=None, description="mass_recruiter | consulting | product"),
):
    """Every recruiter, optionally filtered by tier."""
    response.headers["Cache-Control"] = _CACHE_CONTROL
    companies = load_catalogue().companies
    if tier:
        companies = [c for c in companies if c.tier == tier]
    return companies


@router.get("/{slug}", response_model=Company)
async def company_detail(
    slug: str,
    response: Response,
    current_user: CurrentUser,  # noqa: ARG001
):
    company = get_company(slug)
    if company is None:
        raise HTTPException(status_code=404, detail=f"No recruiter '{slug}' in the catalogue.")
    response.headers["Cache-Control"] = _CACHE_CONTROL
    return company


@router.get("/{slug}/roadmap", response_model=Roadmap)
async def company_roadmap(
    slug: str,
    current_user: CurrentUser,  # noqa: ARG001
    weeks: int = Query(default=8, ge=1, le=52),
    hours_per_week: int = Query(default=10, ge=1, le=60),
    start: dt.date | None = Query(
        default=None,
        description="Plan start date. Defaults to today.",
    ),
):
    """
    A dated study plan, weighted by what this company's assessment actually tests.

    Deliberately NOT cached at the edge: the plan is dated from `start`, so a
    response cached today would hand tomorrow's visitor a plan that begins
    yesterday.
    """
    company = get_company(slug)
    if company is None:
        raise HTTPException(status_code=404, detail=f"No recruiter '{slug}' in the catalogue.")

    return build_roadmap(
        company,
        weeks=weeks,
        hours_per_week=hours_per_week,
        start=start,
    )


# ─── Progress ─────────────────────────────────────────────────────────────────


class ProgressState(BaseModel):
    """Which subtopics this candidate has completed."""

    completed: list[str]
    #: Total minutes of study represented by what they have ticked off. Computed
    #: server-side from the subtopic estimates so the number cannot drift between
    #: clients.
    minutes_done: int = 0


class ToggleProgressRequest(BaseModel):
    subtopic_id: str
    completed: bool
    company_slug: str | None = None


async def _progress_state(db: AsyncSession, user_id) -> ProgressState:
    from app.models.prep import PrepProgress  # noqa: PLC0415
    from app.services.prep import load_subtopics  # noqa: PLC0415

    rows = await db.scalars(
        select(PrepProgress.subtopic_id).where(PrepProgress.user_id == user_id)
    )
    done = set(rows)

    minutes = sum(
        s.minutes
        for items in load_subtopics().subtopics.values()
        for s in items
        if s.id in done
    )
    return ProgressState(completed=sorted(done), minutes_done=minutes)


@router.get("/me/progress", response_model=ProgressState)
async def get_progress(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Everything this candidate has ticked off, across every company plan.

    "/me/progress" is two segments and does not collide with "/{slug}" (one
    segment) or "/{slug}/roadmap" (whose second segment is the literal "roadmap"),
    so declaration order does not matter here — verified by asserting this path
    resolves to 401 rather than 404.
    """
    return await _progress_state(db, current_user.user_id)


@router.post("/me/progress", response_model=ProgressState)
async def toggle_progress(
    request: ToggleProgressRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a subtopic done or not done.

    Idempotent in both directions: ticking something already ticked is a no-op
    rather than a duplicate row (the unique constraint would reject it anyway),
    and un-ticking something that was never ticked is a no-op rather than a 404.
    A checkbox that errors on a double-tap is a checkbox nobody trusts.

    Returns the WHOLE state rather than just the change, so the client never has
    to reconstruct it locally and can never drift from the server.
    """
    from app.models.prep import PrepProgress  # noqa: PLC0415

    if request.completed:
        existing = await db.scalar(
            select(PrepProgress).where(
                PrepProgress.user_id == current_user.user_id,
                PrepProgress.subtopic_id == request.subtopic_id,
            )
        )
        if existing is None:
            db.add(
                PrepProgress(
                    user_id=current_user.user_id,
                    subtopic_id=request.subtopic_id,
                    company_slug=request.company_slug,
                    completed_at=dt.datetime.now(dt.UTC),
                )
            )
    else:
        await db.execute(
            delete(PrepProgress).where(
                PrepProgress.user_id == current_user.user_id,
                PrepProgress.subtopic_id == request.subtopic_id,
            )
        )

    await db.commit()
    logger.info(
        "prep_progress_toggled",
        user_id=str(current_user.user_id),
        subtopic=request.subtopic_id,
        completed=request.completed,
    )
    return await _progress_state(db, current_user.user_id)
