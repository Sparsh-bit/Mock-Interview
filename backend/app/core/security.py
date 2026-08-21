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
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from redis.asyncio import Redis

from app.core.config import settings
from app.db.redis import get_redis
from app.db.session import AsyncSession, get_db

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired authentication token.",
    headers={"WWW-Authenticate": "Bearer"},
)

_HS_ALGORITHMS = {"HS256", "HS384", "HS512"}

#: Asymmetric algorithms this service will accept. An allowlist, because the
#: alternative is trusting the token's own header to say how it should be verified.
#:
#: Supabase signs with ES256 (current projects) or RS256 (older ones). Anything else —
#: "none" above all — is refused before a key is even looked up. The classic
#: algorithm-confusion attack is narrower here than usual, because each branch already
#: uses a branch-appropriate key source rather than one shared key, but "the attack we
#: can think of does not work" is a weaker property than "only the two algorithms we
#: actually issue are accepted".
_ASYMMETRIC_ALGORITHMS = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}


def _unverified_jwt_allowed() -> bool:
    """
    May this process accept a token WITHOUT verifying its signature?

    Reading an unverified token means anyone can mint any identity, so this is a total
    auth bypass and it needs to be impossible to enable by accident.

    It used to be gated on `settings.is_development` alone — and ENVIRONMENT defaults to
    "development". So a deployment that simply forgot to set ENVIRONMENT=production
    accepted forged tokens the moment the JWT secret was missing or the JWKS endpoint
    was briefly unreachable, with nothing in the logs saying auth had been disabled.
    Two independent conditions now have to hold, one of which nobody sets by omission.
    """
    return settings.ALLOW_UNVERIFIED_JWT and settings.is_development

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
    if alg not in _HS_ALGORITHMS and alg not in _ASYMMETRIC_ALGORITHMS:
        # Covers alg:"none" and every other unexpected value, before any key lookup.
        logger.warning("jwt_algorithm_not_permitted", alg=alg)
        raise CREDENTIALS_EXCEPTION

    if alg in _HS_ALGORITHMS:
        secret_unconfigured = (
            not settings.SUPABASE_JWT_SECRET or settings.SUPABASE_JWT_SECRET == "your-jwt-secret"
        )
        if secret_unconfigured:
            if not _unverified_jwt_allowed():
                logger.error("jwt_secret_unconfigured_refusing_unverified_token")
                raise CREDENTIALS_EXCEPTION
            return jwt.get_unverified_claims(token)

        try:
            return jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                # The whole HS set, not the header's claim. Narrowing to `alg` would be
                # taking the attacker's word for which algorithm to use; both are inside
                # the allowlist checked above, so this only removes the header as an input.
                algorithms=sorted(_HS_ALGORITHMS),
                audience=settings.SUPABASE_JWT_AUDIENCE,
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
        if _unverified_jwt_allowed():
            return jwt.get_unverified_claims(token)
        raise CREDENTIALS_EXCEPTION from exc

    matching_key = next((k for k in keys if k.get("kid") == kid), None)
    if matching_key is None:
        logger.warning("jwks_no_matching_key", kid=kid)
        raise CREDENTIALS_EXCEPTION

    try:
        # The KEY declares its algorithm; the token does not get a say. The old
        # `matching_key.get("alg", alg)` fell back to the header when a JWKS entry omitted
        # `alg`, which handed that decision back to the caller.
        key_alg = matching_key.get("alg")
        if key_alg not in _ASYMMETRIC_ALGORITHMS:
            logger.warning("jwks_key_algorithm_not_permitted", kid=kid, alg=key_alg)
            raise CREDENTIALS_EXCEPTION
        return jwt.decode(
            token,
            matching_key,
            algorithms=[key_alg],
            audience=settings.SUPABASE_JWT_AUDIENCE,
        )
    except JWTError as exc:
        logger.warning("jwt_verification_failed", error=str(exc), alg=alg)
        raise CREDENTIALS_EXCEPTION from exc


#: Routes a suspended account must still reach.
#:
#: An automated ban with no route out is indefensible, and these two ARE the route out: the
#: balance endpoint is how the client learns it is banned and why, and the appeal is the
#: request for review. Blocking either would leave a wrongly-banned paying user with nothing
#: but a support email.
_BAN_EXEMPT_SUFFIXES = ("/billing/me", "/billing/appeal", "/auth/profile")


def _is_ban_exempt(path: str) -> bool:
    return any(path.endswith(s) for s in _BAN_EXEMPT_SUFFIXES)


async def _is_banned(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Is this account already suspended? Cheap indexed read on the per-user row."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.billing import UserPlan  # noqa: PLC0415

    return bool(
        await db.scalar(
            select(UserPlan.is_banned).where(UserPlan.user_id == user_id)
        )
    )


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
    request: Request = None,  # type: ignore[assignment]  # noqa: B008
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),  # noqa: B008
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

    # CREDENTIAL SHARING — same choke point, same reasoning as `is_active` above.
    #
    # Enforcing this per-endpoint would mean auditing every route forever and missing the
    # next one; here it covers everything by construction.
    #
    # TWO PATHS ARE EXEMPT AND MUST STAY EXEMPT. A banned user has to be able to read their
    # own balance — that is how the UI learns it is banned and shows the appeal — and has to
    # be able to submit the appeal itself. Blocking those would mean the only route out of a
    # wrong ban is an email nobody reads, which is what makes an automated ban indefensible.
    if request is not None and not _is_ban_exempt(request.url.path):
        from app.services.security.sharing import client_ip, record_and_check  # noqa: PLC0415

        verdict = await record_and_check(
            db,
            redis,
            user.id,
            client_ip(dict(request.headers), request.client.host if request.client else None),
            request.headers.get("user-agent"),
        )
        # The row is written inside the caller's transaction; commit it here because this
        # dependency is not the request handler and nothing downstream is obliged to.
        with contextlib.suppress(Exception):
            await db.commit()

        if verdict.banned or await _is_banned(db, user.id):
            logger.warning("auth_rejected_banned_account", user_id=str(user.id))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This account is suspended because it was used from two places at "
                    "once. You can request a review from your account page."
                ),
            )

    # TEMPORARY (token counter) — tag any AI spend during this request with the
    # user who caused it. Removed with the rest of the ledger; see
    # docs/TEMPORARY-token-counter.md.
    #
    # Set without a matching reset on purpose. Starlette runs each request in its
    # own asyncio task and contextvars are copied per task, so this value is
    # visible to everything downstream in THIS request and to nothing else. A
    # local import keeps core/ from depending on services/ at module load, so
    # deleting the ledger is a one-line change here.
    with contextlib.suppress(Exception):
        from app.services.ai.usage import current_user_id, current_user_is_admin  # noqa: PLC0415

        current_user_id.set(user.id)
        # Set here because this is the only place the User ROW is in hand. The per-user AI
        # budget exempts admins for the reason credits.py spells out — an operator who is
        # metered runs out mid-support-ticket and starts testing on a spare account, or
        # worse, keeps testing on the standby model without noticing.
        current_user_is_admin.set(bool(getattr(user, "is_admin", False)))

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
