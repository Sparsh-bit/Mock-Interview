"""
Security — core/security.py

JWT verification for Supabase-issued access tokens.
All protected API endpoints use get_current_user() as a FastAPI dependency.

Supabase projects sign access tokens one of two ways, and we must support
both since which one is active is a per-project setting, not something we
control:
  - Legacy shared-secret HS256 (SUPABASE_JWT_SECRET, symmetric).
  - Newer JWT Signing Keys, asymmetric (ES256/RS256), verified against the
    project's public JWKS at {SUPABASE_URL}/auth/v1/.well-known/jwks.json.
We inspect the token header's `alg` to decide which path applies, rather
than hardcoding one algorithm -- a project on JWKS-based signing will
never present an HS256 token, so this is a clean either/or, not a guess.

The unverified-claims fallback only applies in development when neither a
usable secret nor a reachable JWKS is available. Any verification failure
otherwise fails closed with a 401.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from typing import Annotated, Any

import httpx
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

_HS_ALGORITHMS = {"HS256", "HS384", "HS512"}

# ─── JWKS cache ────────────────────────────────────────────────────────────
# Supabase's signing keys rotate rarely; a short in-process cache avoids a
# network round-trip on every request without risking long-lived staleness.
_JWKS_CACHE_TTL_SECONDS = 600
_jwks_cache: dict[str, Any] = {"keys": [], "fetched_at": 0.0}


async def _get_jwks() -> list[dict[str, Any]]:
    now = time.monotonic()
    if now - _jwks_cache["fetched_at"] < _JWKS_CACHE_TTL_SECONDS and _jwks_cache["keys"]:
        return _jwks_cache["keys"]

    url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url, headers={"apikey": settings.SUPABASE_ANON_KEY})
        response.raise_for_status()
        keys = response.json().get("keys", [])

    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = now
    return keys


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


async def verify_supabase_jwt(token: str) -> dict:
    """
    Decode and verify a Supabase JWT, routing to the correct verification
    path based on the token's own `alg` header rather than assuming one:
      - HS256/384/512 -> legacy shared-secret verification.
      - Anything else (ES256, RS256, ...) -> JWKS public-key verification.

    Falls back to unverified claim parsing only in development when the
    applicable verification method has no usable key configured/reachable.
    Any other failure fails closed with a 401.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        logger.warning("jwt_header_decode_failed", error=str(exc))
        raise CREDENTIALS_EXCEPTION from exc

    alg = header.get("alg", "")

    if alg in _HS_ALGORITHMS:
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
                algorithms=[alg],
                options={"verify_aud": False},
            )
        except JWTError as exc:
            logger.warning("jwt_verification_failed", error=str(exc), alg=alg)
            raise CREDENTIALS_EXCEPTION from exc

    # Asymmetric algorithm -- verify against the project's JWKS.
    kid = header.get("kid")
    try:
        keys = await _get_jwks()
    except Exception as exc:  # network error, bad JWKS response, etc.
        logger.error("jwks_fetch_failed", error=str(exc))
        if settings.is_development:
            return jwt.get_unverified_claims(token)
        raise CREDENTIALS_EXCEPTION from exc

    matching_key = next((k for k in keys if k.get("kid") == kid), None)
    if matching_key is None:
        logger.warning("jwks_no_matching_key", kid=kid)
        raise CREDENTIALS_EXCEPTION

    try:
        return jwt.decode(
            token,
            matching_key,
            algorithms=[matching_key.get("alg", alg)],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        logger.warning("jwt_verification_failed", error=str(exc), alg=alg)
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

    claims = await verify_supabase_jwt(credentials.credentials)

    supabase_uid: str = claims.get("sub", "")
    email: str = claims.get("email", "")

    if not supabase_uid:
        raise CREDENTIALS_EXCEPTION

    # Load application user record
    from sqlalchemy import select

    from app.models.user import Profile, User

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

    # Deactivated accounts are refused here, at the one choke point every
    # authenticated request passes through.
    #
    # `users.is_active` existed as a column that nothing wrote and nothing read —
    # so before this check, an admin "deactivating" someone would have flipped a
    # boolean and changed nothing at all about what they could do. Enforcing it
    # anywhere other than here would mean auditing every endpoint forever.
    #
    # 403 with a specific message, not 401: the token is perfectly valid, so a
    # 401 would send the client into a refresh-and-retry loop against an account
    # that is never coming back. The client can tell the difference and show
    # something true.
    if not user.is_active:
        logger.info("auth_rejected_deactivated_account", user_id=str(user.id))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact support if you think this is a mistake.",
        )

    # TEMPORARY (token counter) — tag any AI spend during this request with the
    # user who caused it. Removed with the rest of the ledger; see
    # TEMPORARY-token-counter.md.
    #
    # Set without a matching reset on purpose. Starlette runs each request in its
    # own asyncio task and contextvars are copied per task, so this value is
    # visible to everything downstream in THIS request and to nothing else. A
    # local import keeps core/ from depending on services/ at module load, so
    # deleting the ledger is a one-line change here.
    with contextlib.suppress(Exception):
        from app.services.ai.usage import current_user_id  # noqa: PLC0415

        current_user_id.set(user.id)

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
        # Logged at WARNING, with the account named. A non-admin reaching an
        # admin route is either a bug in the client or somebody probing, and
        # neither used to leave any trace at all — the refusal was silent, so a
        # sustained attempt to find an unguarded admin endpoint was invisible.
        logger.warning(
            "admin_access_denied",
            user_id=str(current_user.user_id),
            email=current_user.email,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )

    return current_user


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
AdminUser = Annotated[AuthenticatedUser, Depends(get_current_admin_user)]
