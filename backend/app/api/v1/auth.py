"""
Auth Endpoints — api/v1/auth.py

POST /api/v1/auth/profile   — Sync Supabase auth user to application DB (called on first login)
GET  /api/v1/auth/me        — Get current authenticated user profile
POST /api/v1/auth/logout    — Invalidate session (Redis token blacklist)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.core.security import CurrentUser
from app.db.session import AsyncSession, get_db
from fastapi import Depends
from app.models.user import Profile, User

logger = structlog.get_logger(__name__)
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────


class SyncProfileRequest(BaseModel):
    """Sent by the frontend immediately after Supabase auth confirms a new user."""
    full_name: str | None = None
    avatar_url: str | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_admin: bool
    created_at: datetime
    profile: "ProfileResponse | None"


class ProfileResponse(BaseModel):
    full_name: str | None
    avatar_url: str | None
    bio: str | None
    target_company: str | None
    experience_years: int | None
    linkedin_url: str | None
    github_url: str | None


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "/profile",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync Supabase auth user to application DB",
)
async def sync_profile(
    body: SyncProfileRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by the frontend after every successful Supabase auth event (login / register).
    Idempotent — safe to call multiple times for the same user.

    Creates the application-level User + Profile records if they don't exist.
    Updates profile data if they do exist.
    """
    # Check if user already exists
    result = await db.execute(
        select(User).where(User.supabase_uid == current_user.supabase_uid)
    )
    user = result.scalar_one_or_none()

    if user is None:
        # First login — create user + profile
        user = User(
            supabase_uid=current_user.supabase_uid,
            email=current_user.email,
        )
        db.add(user)
        await db.flush()  # Get the user.id without committing

        profile = Profile(
            user_id=user.id,
            full_name=body.full_name,
            avatar_url=body.avatar_url,
        )
        db.add(profile)

        logger.info(
            "user_created",
            user_id=str(user.id),
            email=user.email,
        )
    else:
        # Returning user — update profile if fields provided
        result = await db.execute(
            select(Profile).where(Profile.user_id == user.id)
        )
        profile = result.scalar_one_or_none()

        if profile and (body.full_name or body.avatar_url):
            if body.full_name:
                profile.full_name = body.full_name
            if body.avatar_url:
                profile.avatar_url = body.avatar_url

        logger.info("user_profile_synced", user_id=str(user.id))

    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        created_at=user.created_at,
        profile=ProfileResponse(
            full_name=profile.full_name if profile else None,
            avatar_url=profile.avatar_url if profile else None,
            bio=profile.bio if profile else None,
            target_company=profile.target_company if profile else None,
            experience_years=profile.experience_years if profile else None,
            linkedin_url=profile.linkedin_url if profile else None,
            github_url=profile.github_url if profile else None,
        ) if profile else None,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's profile."""
    from sqlalchemy.orm import selectinload  # noqa: PLC0415

    result = await db.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(User.id == current_user.user_id)
    )
    user = result.scalar_one()

    profile = user.profile
    return UserResponse(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        created_at=user.created_at,
        profile=ProfileResponse(
            full_name=profile.full_name if profile else None,
            avatar_url=profile.avatar_url if profile else None,
            bio=profile.bio if profile else None,
            target_company=profile.target_company if profile else None,
            experience_years=profile.experience_years if profile else None,
            linkedin_url=profile.linkedin_url if profile else None,
            github_url=profile.github_url if profile else None,
        ) if profile else None,
    )
