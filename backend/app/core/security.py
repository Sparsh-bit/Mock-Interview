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

#: Shortest gap between two refetches triggered by an unrecognised key id.
#:
#: THE TRIGGER IS ATTACKER-CONTROLLED, which is the whole reason this number exists. A token
#: can carry any `kid` at all, so "refetch when the kid is unknown" without a floor turns
#: every forged token into a request to Supabase's JWKS endpoint — a rate limit somebody else
#: enforces, reached through our auth path. 30s is far below a rotation's cost (ten minutes
#: of failed logins) and far above what a flood could exploit.
_JWKS_REFETCH_COOLDOWN_SECONDS = 30

_jwks_cache: dict[str, Any] = {"keys": [], "fetched_at": 0.0, "refetched_at": 0.0}


def reset_jwks_cache() -> None:
    """Drop the cached keys. Used by tests, and by nothing on the request path."""
    _jwks_cache.update({"keys": [], "fetched_at": 0.0, "refetched_at": 0.0})


async def _fetch_jwks() -> list[dict[str, Any]]:
    """The network call, by itself, so the caching policy above it can be tested without one."""
    url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url, headers={"apikey": settings.SUPABASE_ANON_KEY})
        response.raise_for_status()
        return response.json().get("keys", [])


async def get_signing_keys(kid: str | None = None) -> list[dict[str, Any]]:
    """
    Supabase's public signing keys, cached for _JWKS_CACHE_TTL_SECONDS.

    REFETCHES WHEN ASKED FOR A KEY ID IT DOES NOT HOLD. Without that the cache had exactly
    one way to notice a rotation — waiting out the ten-minute timer — and every request in
    that window is a 401 on a perfectly valid token.

    That was already true of a single instance. What N replicas add is that each holds its
    own independent timer, so the symptom stops being "everybody is logged out for ten
    minutes" (bad, but obvious, and it ends) and becomes "logins fail at random depending on
    which replica answers", which looks like an intermittent auth bug rather than a rotation.

    The refetch is rate-limited: see _JWKS_REFETCH_COOLDOWN_SECONDS for why that is a
    security property and not a politeness.
    """
    now = time.monotonic()
    fresh = now - _jwks_cache["fetched_at"] < _JWKS_CACHE_TTL_SECONDS and _jwks_cache["keys"]

    if fresh:
        known = any(k.get("kid") == kid for k in _jwks_cache["keys"])
        if kid is None or known:
            return _jwks_cache["keys"]
        if now - _jwks_cache["refetched_at"] < _JWKS_REFETCH_COOLDOWN_SECONDS:
            return _jwks_cache["keys"]
        _jwks_cache["refetched_at"] = now
        logger.info("jwks_refetch_for_unknown_kid", kid=kid)

    keys = await _fetch_jwks()
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
        keys = await get_signing_keys(kid)
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

    # CREDENTIAL-SHARING DETECTION USED TO RUN HERE, AND IT IS GONE ON PURPOSE.
    #
    # It suspended accounts for being used from two IP prefixes at once. The intent was sound
    # and the dampeners were thoughtful, but the population it actually hit was the honest one:
    # candidates on phones moving between college wi-fi and mobile data, behind two layers of
    # NAT. Worse, the strike counter incremented per REQUEST rather than per overlap, and an
    # interview makes several requests a second — so one network handover mid-interview
    # suspended the account and took `/complete` with it. That was observed in production, in a
    # console log where ERR_NETWORK_CHANGED is followed immediately by 403s on /panel/turn,
    # /interview/next and /complete.
    #
    # Removed at the owner's direction rather than tuned again. The judgement is theirs to
    # make: a shared account costs one subscription, and a false suspension costs a candidate
    # the interview they were sitting — and this product's users sit them once, on a scheduled
    # day, with no second attempt.
    #
    # `UserPlan.is_banned` and its companion columns are deliberately LEFT IN PLACE and are
    # now inert: nothing reads them to gate anything, so an account still carrying the flag
    # from before this change is no longer blocked by it and needs no cleanup. Keeping the
    # columns also means no migration, and the history of what happened stays readable.

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
