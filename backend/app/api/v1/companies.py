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
from fastapi import APIRouter, HTTPException, Query, Response

from app.core.security import CurrentUser
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
