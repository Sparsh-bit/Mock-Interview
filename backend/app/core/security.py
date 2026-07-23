"""
Security — core/security.py

JWT verification for Supabase-issued access tokens.
All protected API endpoints use get_current_user() as a FastAPI dependency.

Supabase JWTs are HS256 tokens signed with the project's JWT secret.
We verify them locally; the unverified-claims fallback only applies in development when the
secret is unconfigured/placeholder. Any verification failure, or a missing secret outside
development, fails closed with a 401.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.db.session import AsyncSession, get_db

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired authentication token.",
    headers={"WWW-Authenticate": "Bearer"},
)


class AuthenticatedUser:
    """
    Lightweight user representation extracted from a verified JWT.
    Populated before any route handler runs.
    """

    def __init__(self, user_id: uuid.UUID, supabase_uid: str, email: str) -> None:
        self.user_id = user_id
        self.supabase_uid = supabase_uid
        self.email = email

    def __repr__(self) -> str:
        return f"<AuthenticatedUser id={self.user_id} email={self.email}>"


def verify_supabase_jwt(token: str) -> dict:
    """
    Decode and verify a Supabase JWT.
    Falls back to unverified claim parsing only in development with an unconfigured/placeholder
    secret. Any other case (production, or a configured secret that fails verification) fails closed.
    """
    secret_unconfigured = (
        not settings.SUPABASE_JWT_SECRET or settings.SUPABASE_JWT_SECRET == "your-jwt-secret"
    )

    if secret_unconfigured:
        if not settings.is_development:
            logger.error("jwt_secret_unconfigured_in_non_development")
            raise CREDENTIALS_EXCEPTION
        return jwt.get_unverified_claims(token)

    try:
        return jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        logger.warning("jwt_verification_failed", error=str(exc))
        raise CREDENTIALS_EXCEPTION from exc


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    """
    FastAPI dependency — extracts and returns the authenticated user.
    Auto-creates the application user record in PostgreSQL if it doesn't exist yet.
    """
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_EXCEPTION

    claims = verify_supabase_jwt(credentials.credentials)

    supabase_uid: str = claims.get("sub", "")
    email: str = claims.get("email", "")

    if not supabase_uid:
        raise CREDENTIALS_EXCEPTION

    # Load application user record
    from sqlalchemy import select
    from app.models.user import User, Profile

    result = await db.execute(
        select(User).where(User.supabase_uid == supabase_uid)
    )
    user = result.scalar_one_or_none()

    if user is None:
        try:
            user_uuid = uuid.UUID(supabase_uid)
        except ValueError:
            user_uuid = uuid.uuid4()

        user = User(
            id=user_uuid,
            supabase_uid=supabase_uid,
            email=email,
        )
        db.add(user)
        try:
            await db.flush()
            # Also create profile record
            profile = Profile(
                user_id=user.id,
                full_name=email.split("@")[0] if email else "User",
            )
            db.add(profile)
            await db.commit()
            await db.refresh(user)
        except Exception:
            await db.rollback()
            res = await db.execute(select(User).where(User.supabase_uid == supabase_uid))
            user = res.scalar_one_or_none()
            if not user:
                raise CREDENTIALS_EXCEPTION

    return AuthenticatedUser(
        user_id=user.id,
        supabase_uid=supabase_uid,
        email=email,
    )


async def get_current_admin_user(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    from sqlalchemy import select
    from app.models.user import User

    result = await db.execute(
        select(User.is_admin).where(User.id == current_user.user_id)
    )
    is_admin = result.scalar_one_or_none()

    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )

    return current_user


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
AdminUser = Annotated[AuthenticatedUser, Depends(get_current_admin_user)]
