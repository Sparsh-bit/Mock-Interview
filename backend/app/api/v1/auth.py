"""
Auth Endpoints — api/v1/auth.py

POST /api/v1/auth/profile   — Sync Supabase auth user to application DB (called on first login)
GET  /api/v1/auth/me        — Get current authenticated user profile
POST /api/v1/auth/logout    — Invalidate session (Redis token blacklist)
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import settings
from app.core.rate_limit import ip_rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys
from app.db.session import AsyncSession, get_db
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
    profile: ProfileResponse | None


class ProfileResponse(BaseModel):
    full_name: str | None
    avatar_url: str | None
    bio: str | None
    target_company: str | None
    experience_years: int | None
    linkedin_url: str | None
    github_url: str | None


# ─── Endpoints ────────────────────────────────────────────────────────────────


#: ── THE ACCOUNT-CREATION SURFACE, AND IT HAD NO LIMIT ──────────────────────────
#:
#: This endpoint is called after every successful Supabase auth event and is what writes
#: the application's `users` row, so it is where a script minting accounts arrives — once
#: per account, from one place, with a different perfectly-valid token every time.
#:
#: KEYED ON THE ADDRESS, NOT THE USER, for exactly that reason: the user id is the thing
#: the attacker is varying. `docs/COMPLIANCE.md` records a standing decision against IP
#: keying and it is right for authenticated routes, which is why `core/client_ip.py` only
#: reads a proxy header when a trusted proxy is configured to have written it.
#:
#: TWO WINDOWS. The minute bucket paces a burst; the hour bucket bounds a slow grind, which
#: a per-minute limit alone does nothing about.
#:
#: WHAT THIS IS NOT. It is not a credential-stuffing defence for LOGIN. Login, signup and
#: password reset are Supabase GoTrue calls made straight from the browser and never reach
#: this application — that gap is a console setting and is recorded as a human blocker in
#: docs/SECURITY-REVIEW.md (SR-2026Q3-04) rather than papered over here.
_auth_provision_rate_limit = ip_rate_limiter(
    limit=settings.RATE_LIMIT_AUTH_PER_MINUTE,
    window_seconds=60,
    key_builder=CacheKeys.rate_limit_auth_ip,
    action="creating an account",
)
_auth_provision_hourly_limit = ip_rate_limiter(
    limit=settings.RATE_LIMIT_AUTH_PER_HOUR,
    window_seconds=3600,
    key_builder=lambda ip: f"{CacheKeys.rate_limit_auth_ip(ip)}:hourly",
    action="creating an account",
)


@router.post(
    "/profile",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync Supabase auth user to application DB",
    dependencies=[
        Depends(_auth_provision_rate_limit),
        Depends(_auth_provision_hourly_limit),
    ],
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

        profile: Profile | None = Profile(
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
        # May legitimately be None: a user row can exist without a profile row
        # (created before profiles, or a partial signup). The response below
        # handles that; the annotation on the create branch above makes it
        # explicit rather than leaving the two branches to disagree.
        profile = await db.scalar(
            select(Profile).where(Profile.user_id == user.id)
        )

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
