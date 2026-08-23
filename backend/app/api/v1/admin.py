"""
Admin — user management. api/v1/admin.py

Who is using the product, what they cost, and the two switches that matter:
activate/deactivate an account, and grant/revoke admin.

DEACTIVATION IS REAL. `users.is_active` used to be a column nothing wrote and
nothing read, so flipping it changed nothing. It is now enforced in
`core.security.get_current_user`, the single choke point every authenticated
request passes through — a deactivated account gets a 403 on its next request,
whatever endpoint it calls. That enforcement is the feature; this router is just
the switch.

TWO GUARDRAILS AGAINST LOCKING YOURSELF OUT. An admin cannot deactivate their own
account and cannot revoke their own admin rights. Both are trivially easy to do
by accident on a list of similar-looking rows, and both are unrecoverable from
the UI — the fix would be a manual SQL UPDATE against production, which is
exactly the situation an admin panel exists to avoid.

EVERY MUTATION IS AUDITED. Changing someone's access is the kind of action that
gets questioned later, so each one writes an `audit_logs` row naming the actor,
the target, the before and after. The table is append-only by design.

THERE IS ONE BULK PERSONAL-DATA READ IN HERE AND IT IS TREATED AS ONE. `GET /marketing`
returns every candidate's email address in a single response, because the owner mails those
people by hand and a mail merge needs the whole list rather than the page you happen to be
on. It is gated by the same `AdminUser` dependency as everything else, it has its own
rate-limit bucket so an export loop cannot eat the budget the deactivate button needs, and it
carries counts and flags only — never an answer, a transcript, a report or a score. Read the
long comment above `_MARKETING_MAX_ROWS` before adding a field to it.

THE COST COLUMN IS TEMPORARY DATA IN A PERMANENT PAGE. Per-user spend is read
from `ai_usage`, which is scheduled for deletion once credits ship — see
docs/TEMPORARY-token-counter.md. The queries degrade to zero rather than failing when
that table is gone, so removing the ledger does not break this page; the column
just needs repointing at whatever billing records instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import AdminUser
from app.db.redis import CacheKeys
from app.db.session import get_db
from app.models.billing import CreditEvent
from app.models.report import Report
from app.models.session import InterviewSession, SessionStatus
from app.models.system import AuditLog
from app.models.user import Profile, User
from app.services.billing.credits import KIND_PURCHASE
from app.services.billing.plans import (
    FEATURE_LABELS,
    FEATURES,
    get_item,
    trial_allowance,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

# Mutations only. Reads are cheap and idempotent; a write here changes who can use
# the product, and 30/minute is far above any human clicking through a table while
# still bounding a runaway script or a compromised admin token to something a
# human would notice in the audit log rather than a silent mass lockout.
_admin_write_rate_limit = rate_limiter(
    limit=30,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_admin(user_id),
    action="changing user access",
)


class UserRow(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    is_admin: bool
    created_at: datetime
    sessions: int
    last_session_at: datetime | None
    #: From the temporary AI ledger; 0 when it is disabled or removed.
    ai_cost_usd: float
    ai_calls: int


class UserListResponse(BaseModel):
    users: list[UserRow]
    total: int
    page: int
    per_page: int
    #: False once the temporary ledger is gone, so the UI can hide the column
    #: instead of showing a row of honest-looking zeroes.
    cost_data_available: bool


class UpdateUserRequest(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None


def _ledger_enabled() -> bool:
    return bool(getattr(settings, "AI_USAGE_LEDGER_ENABLED", False))


async def _cost_by_user(db: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[float, int]]:
    """
    (cost, calls) per user from the temporary ledger.

    Returns {} rather than raising when the ledger is off or its table does not
    exist — this router must outlive it. One grouped query for the whole page, not
    one per row.
    """
    if not _ledger_enabled() or not user_ids:
        return {}
    try:
        from app.models.ai_usage import AIUsage  # noqa: PLC0415

        rows = (
            await db.execute(
                select(
                    AIUsage.user_id,
                    func.coalesce(func.sum(AIUsage.cost_usd), 0),
                    func.count(),
                )
                .where(AIUsage.user_id.in_(user_ids))
                .group_by(AIUsage.user_id)
            )
        ).all()
        return {r[0]: (round(float(r[1] or 0), 6), r[2]) for r in rows}
    except Exception as exc:  # noqa: BLE001 — the ledger is optional by design
        logger.warning("admin_cost_lookup_failed", error=type(exc).__name__)
        return {}



@lru_cache(maxsize=1)
def _admin_storage() -> Any:
    """
    The process-wide Supabase client, built once. Same reasoning as resume.py's: `create_client`
    builds a fresh set of HTTP clients per call, so calling it per request pays a new TLS
    handshake before sending a byte.
    """
    from supabase import create_client  # noqa: PLC0415

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


async def _revoke_supabase_sessions(supabase_uid: str) -> bool:
    """
    Sign a deactivated user out of Supabase everywhere. Best-effort.

    Our own 403 in get_current_user already blocks them on their very next
    request, because that dependency reads is_active from the database every
    time — so this is not what makes deactivation work. What it adds is that
    they stop holding a *valid* access token and stop being able to mint new
    ones from a refresh token. Without it the token stays cryptographically
    valid until it expires, which matters if a token is ever accepted anywhere
    that does not go through our dependency.

    It also signs them out of the browser immediately instead of leaving them
    staring at a UI that 403s on every action.

    Needs the service-role key, so it is server-side only and must never be
    reachable from a request the user controls.
    """
    import httpx  # noqa: PLC0415

    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{supabase_uid}/logout"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                url,
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                },
            )
        # 200 and 204 both mean done; 404 means there was no session to kill,
        # which is the same outcome from here.
        if r.status_code in (200, 204, 404):
            return True
        logger.warning("supabase_logout_unexpected_status", status=r.status_code)
        return False
    except Exception as exc:  # noqa: BLE001 — never block a deactivation on this
        logger.warning("supabase_logout_failed", error=type(exc).__name__)
        return False


@router.get("/users", response_model=UserListResponse, summary="List users with usage and cost")
async def list_users(
    current_user: AdminUser,
    q: str | None = Query(None, max_length=200, description="Match on email or name."),
    active: bool | None = Query(None, description="Filter by account state."),
    sort: Literal["cost", "sessions", "recent", "email"] = Query("cost"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> UserListResponse:
    # Session counts and last-activity per user, as a subquery rather than N
    # queries or a relationship load — this page is a table, and a per-row query
    # is how a table becomes slow the moment it has real data in it.
    sess = (
        select(
            InterviewSession.user_id.label("uid"),
            func.count().label("n"),
            func.max(InterviewSession.created_at).label("last_at"),
        )
        .group_by(InterviewSession.user_id)
        .subquery()
    )

    stmt = (
        select(User, Profile.full_name, sess.c.n, sess.c.last_at)
        .outerjoin(Profile, Profile.user_id == User.id)
        .outerjoin(sess, sess.c.uid == User.id)
    )

    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), Profile.full_name.ilike(like)))
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0

    # Sorting by cost cannot happen in SQL without joining a table that is
    # scheduled for deletion, so the page is ordered by a stable proxy here and
    # re-sorted by cost below, over the page's own rows.
    order = {
        "sessions": func.coalesce(sess.c.n, 0).desc(),
        "recent": func.coalesce(sess.c.last_at, User.created_at).desc(),
        "email": User.email.asc(),
        "cost": func.coalesce(sess.c.n, 0).desc(),
    }[sort]
    stmt = stmt.order_by(order, User.created_at.desc()).limit(per_page).offset((page - 1) * per_page)

    rows = (await db.execute(stmt)).all()
    ids = [r[0].id for r in rows]
    costs = await _cost_by_user(db, ids)

    users = [
        UserRow(
            id=u.id,
            email=u.email,
            full_name=name,
            is_active=u.is_active,
            is_admin=u.is_admin,
            created_at=u.created_at,
            sessions=n or 0,
            last_session_at=last_at,
            ai_cost_usd=costs.get(u.id, (0.0, 0))[0],
            ai_calls=costs.get(u.id, (0.0, 0))[1],
        )
        for u, name, n, last_at in rows
    ]

    if sort == "cost":
        users.sort(key=lambda r: r.ai_cost_usd, reverse=True)

    return UserListResponse(
        users=users,
        total=total,
        page=page,
        per_page=per_page,
        cost_data_available=_ledger_enabled(),
    )


@router.get("/users/{user_id}", summary="One user: usage, cost by feature, recent sessions")
async def get_user_detail(
    user_id: uuid.UUID,
    current_user: AdminUser,
    days: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    name = await db.scalar(select(Profile.full_name).where(Profile.user_id == user_id))
    since = datetime.now(UTC) - timedelta(days=days)

    sessions = (
        await db.execute(
            select(
                InterviewSession.id,
                InterviewSession.status,
                InterviewSession.created_at,
                InterviewSession.questions_asked,
            )
            .where(InterviewSession.user_id == user_id)
            .order_by(InterviewSession.created_at.desc())
            .limit(20)
        )
    ).all()

    by_feature: list[dict] = []
    cost_total = 0.0
    if _ledger_enabled():
        try:
            from app.models.ai_usage import AIUsage  # noqa: PLC0415

            frows = (
                await db.execute(
                    select(
                        AIUsage.feature,
                        func.count(),
                        func.coalesce(func.sum(AIUsage.cost_usd), 0),
                        func.coalesce(func.sum(AIUsage.input_tokens + AIUsage.cached_input_tokens), 0),
                        func.coalesce(func.sum(AIUsage.output_tokens), 0),
                    )
                    .where(AIUsage.user_id == user_id, AIUsage.created_at >= since)
                    .group_by(AIUsage.feature)
                    .order_by(func.coalesce(func.sum(AIUsage.cost_usd), 0).desc())
                )
            ).all()
            by_feature = [
                {
                    "feature": r[0],
                    "calls": r[1],
                    "cost_usd": round(float(r[2] or 0), 6),
                    "input_tokens": r[3] or 0,
                    "output_tokens": r[4] or 0,
                }
                for r in frows
            ]
            cost_total = round(sum(f["cost_usd"] for f in by_feature), 6)
        except Exception as exc:  # noqa: BLE001
            logger.warning("admin_user_cost_failed", error=type(exc).__name__)

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": name,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "created_at": user.created_at,
        },
        "window_days": days,
        "cost_data_available": _ledger_enabled(),
        "ai_cost_usd": cost_total,
        "by_feature": by_feature,
        "recent_sessions": [
            {
                "id": s[0],
                "status": getattr(s[1], "value", s[1]),
                "created_at": s[2],
                "questions_asked": s[3] or 0,
            }
            for s in sessions
        ],
    }


@router.patch(
    "/users/{user_id}",
    summary="Activate/deactivate, or grant/revoke admin",
    dependencies=[Depends(_admin_write_rate_limit)],
)
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    current_user: AdminUser,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    if body.is_active is None and body.is_admin is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nothing to change — pass is_active and/or is_admin.",
        )

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # ── Lockout guardrails ───────────────────────────────────────────────────
    # Both of these are one misclick away on a table of similar rows, and neither
    # is recoverable from this UI — undoing them needs a manual UPDATE against
    # production, which is the scenario an admin panel exists to prevent.
    if user.id == current_user.user_id:
        if body.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account.",
            )
        if body.is_admin is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot revoke your own admin access.",
            )

    # Never leave the platform with no admin. Checked as a count rather than by
    # inspecting this one row, because the dangerous case is demoting somebody
    # else while you are the only other admin — and then losing your own access.
    if body.is_admin is False and user.is_admin:
        remaining = await db.scalar(
            select(func.count()).select_from(User).where(User.is_admin.is_(True), User.id != user.id)
        )
        if not remaining:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This is the last admin account — promote someone else first.",
            )

    before = {"is_active": user.is_active, "is_admin": user.is_admin}
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    after = {"is_active": user.is_active, "is_admin": user.is_admin}

    if before != after:
        # Append-only record of who changed whose access, and to what.
        db.add(
            AuditLog(
                user_id=current_user.user_id,
                action="admin.user_updated",
                entity_type="user",
                entity_id=user.id,
                ip_address=(request.client.host if request.client else None),
                user_agent=request.headers.get("user-agent"),
                payload={
                    "target_email": user.email,
                    "actor_email": current_user.email,
                    "before": before,
                    "after": after,
                },
            )
        )
        logger.info(
            "admin_user_updated",
            actor=str(current_user.user_id),
            target=str(user.id),
            before=before,
            after=after,
        )

    await db.commit()

    # Deactivation only: kill their Supabase sessions so they are signed out now
    # and cannot mint a fresh access token from a refresh token. Deliberately
    # after the commit — the flag is what enforces the block, and a failure here
    # must not roll the deactivation back.
    signed_out = None
    if before["is_active"] and after["is_active"] is False:
        signed_out = await _revoke_supabase_sessions(user.supabase_uid)

    return {
        "id": user.id,
        "email": user.email,
        **after,
        "sessions_revoked": signed_out,
    }


async def _delete_supabase_user(supabase_uid: str) -> bool:
    """
    Delete the account from Supabase Auth. This is what makes a deletion PERMANENT.

    WITHOUT THIS, DELETION IS COSMETIC. Our `users` row is not the account — the credentials
    live in Supabase's own auth schema, and `get_current_user` creates a local row on first
    sight of a valid token (deliberately, so a user can never be locked out by a signup hook
    that failed months ago). So deleting only our row means the person signs in again, a fresh
    row is created, and they are back — with their data gone but their access intact. That is
    the worst of both outcomes and it would look exactly like the delete button not working.

    Best-effort in the sense that it reports rather than raises, but the CALLER treats a false
    return as fatal and aborts before touching our data. See the ordering note in the endpoint.
    """
    import httpx  # noqa: PLC0415

    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{supabase_uid}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.delete(
                url,
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                },
            )
        # 404 counts as success: the auth user is already gone, which is the state we want and
        # is exactly what a retry of a half-finished deletion looks like.
        if r.status_code in (200, 204, 404):
            return True
        logger.error("supabase_delete_unexpected_status", status=r.status_code)
        return False
    except Exception as exc:  # noqa: BLE001 — reported to the caller, which aborts
        logger.error("supabase_delete_failed", error=type(exc).__name__)
        return False


async def _delete_stored_files(db: AsyncSession, user_id: uuid.UUID) -> int:
    """
    Remove this user's uploaded resumes from storage. Returns how many were removed.

    THE DATABASE CASCADE DOES NOT REACH FILES. `resume_files` rows go when the user does, and
    the objects they point at would stay in the bucket forever — a candidate's CV, still
    stored, referenced by nothing that would ever tell you it exists. For a deletion that is
    the whole point, so this runs first and its failure is not fatal: an orphaned file is worse
    than nothing but far better than a deletion that refuses to proceed.
    """
    from app.models.report import ResumeFile  # noqa: PLC0415

    paths = [
        p
        for p in (
            await db.scalars(select(ResumeFile.storage_path).where(ResumeFile.user_id == user_id))
        ).all()
        if p
    ]
    if not paths:
        return 0

    def _remove() -> None:
        _admin_storage().storage.from_(settings.SUPABASE_STORAGE_BUCKET_RESUMES).remove(paths)

    with contextlib.suppress(Exception):
        # supabase-py is synchronous; called inline it would block the event loop for the
        # duration of the delete, and this can be a handful of multi-megabyte objects.
        await asyncio.to_thread(_remove)
        return len(paths)
    logger.warning("resume_files_not_removed", user_id=str(user_id), count=len(paths))
    return 0


class DeleteUserRequest(BaseModel):
    """
    Confirmation for a destructive, irreversible action.

    THE EMAIL IS REQUIRED AND IS CHECKED SERVER-SIDE against the row being deleted. A
    confirmation the client alone enforces is not a confirmation — the endpoint is reachable
    with a user id and nothing else — and the failure this guards is mundane and permanent:
    the wrong row, deleted from a list where every row looks the same. Typing the address makes
    the admin look at which account they are on.
    """

    #: Must match the target's email exactly, case-insensitively.
    confirm_email: str = Field(min_length=3, max_length=255)
    #: Why. Recorded in the audit log, which outlives the account.
    reason: str = Field(default="", max_length=300)


@router.post(
    "/users/{user_id}/delete",
    summary="Permanently delete an account and everything belonging to it",
    dependencies=[Depends(_admin_write_rate_limit)],
)
async def delete_user(
    user_id: uuid.UUID,
    body: DeleteUserRequest,
    current_user: AdminUser,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Delete an account for good: the Supabase login, the uploaded files, and every row.

    IRREVERSIBLE, AND THE ONLY THING LEFT BEHIND IS THE AUDIT ENTRY. Every table referencing
    `users.id` is already declared either ON DELETE CASCADE — sessions, answers, scores,
    reports, resumes, the credit ledger, redemptions — or ON DELETE SET NULL for records that
    must outlive the person, chiefly `audit_logs`. So one DELETE removes the graph correctly,
    and `entity_id` on the audit row is a plain UUID rather than a foreign key precisely so
    that the record of the deletion is not deleted by it.

    THE ORDER IS CHOSEN FOR WHAT A FAILURE HALFWAY LEAVES BEHIND, and it is the whole design:

      1. FILES first, and a failure here is tolerated. They are unreachable either way once
         the rows are gone, so refusing to proceed would strand the account instead.
      2. THE SUPABASE LOGIN second, and a failure here ABORTS. If the auth user survives our
         data, the person signs in again and `get_current_user` creates them a fresh row —
         access intact, data gone. Deleting our rows first and failing here produces exactly
         that, so it must be attempted while we can still refuse.
      3. OUR ROWS last, in the request transaction, committed by `get_db`. If this fails after
         the auth user is gone, the account is unreachable and re-running the endpoint
         finishes the job: step 2 treats an already-deleted auth user as success.

    Reversing 2 and 3 is the tempting mistake, because it makes the happy path read better.

    POST RATHER THAN DELETE, and not for taste. This needs a body — the typed confirmation —
    and a body on a DELETE is poorly supported end to end: intermediaries are permitted to
    drop it, this app is served through Cloudflare, and the frontend's own ApiClient does not
    accept one on `delete` (which is what surfaced it). A confirmation that can be silently
    stripped in transit is worse than no confirmation, because the endpoint would then see an
    empty string and refuse every legitimate deletion — or, with a laxer check, accept one that
    was never confirmed.

    Three refusals, all server-side:
      * NOT YOURSELF. An admin deleting their own account cannot undo it.
      * NOT THE LAST ADMIN. Counted rather than inferred from this row, because the dangerous
        case is deleting the other admin while assuming you are not the last.
      * THE EMAIL MUST MATCH. See DeleteUserRequest.
    """
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )

    if (body.confirm_email or "").strip().lower() != (user.email or "").strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The email you typed does not match this account. Nothing was deleted.",
        )

    if user.is_admin:
        others = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_admin.is_(True), User.id != user.id)
        )
        if not others:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This is the last admin account — promote someone else first.",
            )

    # Captured BEFORE the delete: after it there is nothing left to describe, and the audit
    # entry is the only remaining record that this account ever existed.
    target_email = user.email
    supabase_uid = user.supabase_uid

    files_removed = await _delete_stored_files(db, user.id)

    if not await _delete_supabase_user(supabase_uid):
        # Refused rather than continued. See the ordering note: proceeding would leave a
        # working login attached to no data, and the next sign-in would silently recreate the
        # account as if nothing had happened.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "The account could not be removed from the login provider, so nothing was "
                "deleted. Try again in a moment."
            ),
        )

    db.add(
        AuditLog(
            user_id=current_user.user_id,
            action="admin.user_deleted",
            entity_type="user",
            # A plain UUID column, not a foreign key — which is what lets this row survive the
            # deletion it describes.
            entity_id=user.id,
            ip_address=(request.client.host if request.client else None),
            user_agent=request.headers.get("user-agent"),
            payload={
                "target_email": target_email,
                "actor_email": current_user.email,
                "reason": body.reason.strip(),
                "resume_files_removed": files_removed,
            },
        )
    )

    await db.delete(user)

    logger.warning(
        "admin_user_deleted",
        actor=str(current_user.user_id),
        target=str(user_id),
        target_email=target_email,
        files_removed=files_removed,
    )
    return {
        "deleted": True,
        "email": target_email,
        "resume_files_removed": files_removed,
    }


@router.get("/audit", summary="Recent admin actions")
async def list_admin_audit(
    current_user: AdminUser,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Admin actions only, not the whole event log. `audit_logs` also carries every
    interview and report event, and mixing those in would bury the handful of
    entries anyone opens this for.
    """
    rows = (
        await db.execute(
            select(AuditLog)
            .where(cast(AuditLog.action, String).like("admin.%"))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "entries": [
            {
                "at": r.created_at,
                "action": r.action,
                "actor": (r.payload or {}).get("actor_email"),
                "target": (r.payload or {}).get("target_email"),
                "before": (r.payload or {}).get("before"),
                "after": (r.payload or {}).get("after"),
                "ip": r.ip_address,
            }
            for r in rows
        ]
    }


@router.get("/overview", summary="Platform totals")
async def admin_overview(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    active_users = await db.scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    ) or 0
    admins = await db.scalar(
        select(func.count()).select_from(User).where(User.is_admin.is_(True))
    ) or 0
    total_sessions = await db.scalar(select(func.count()).select_from(InterviewSession)) or 0

    week = datetime.now(UTC) - timedelta(days=7)
    new_this_week = await db.scalar(
        select(func.count()).select_from(User).where(User.created_at >= week)
    ) or 0

    spend_7d = 0.0
    if _ledger_enabled():
        try:
            from app.models.ai_usage import AIUsage  # noqa: PLC0415

            spend_7d = round(
                float(
                    await db.scalar(
                        select(func.coalesce(func.sum(AIUsage.cost_usd), Decimal("0"))).where(
                            AIUsage.created_at >= week
                        )
                    )
                    or 0
                ),
                6,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("admin_overview_cost_failed", error=type(exc).__name__)

    return {
        "total_users": total_users,
        "active_users": active_users,
        "deactivated_users": total_users - active_users,
        "admins": admins,
        "new_users_7d": new_this_week,
        "total_sessions": total_sessions,
        "ai_spend_7d_usd": spend_7d,
        "cost_data_available": _ledger_enabled(),
        "daily_budget_usd": settings.AI_DAILY_BUDGET_USD,
    }


# ── Revenue ──────────────────────────────────────────────────────────────────────


#: Paise per rupee. Money is summed as integers and divided exactly once, at the edge,
#: because float rupees accumulate error and a revenue figure that disagrees with the
#: payment gateway by a paisa is a figure nobody trusts again.
_PAISE_PER_RUPEE = 100


def _inr(paise: int) -> float:
    """Paise to rupees, for display only. Never fed back into arithmetic."""
    return round(paise / _PAISE_PER_RUPEE, 2)


#: THE MONEY IS IN `detail`, NOT IN `delta`.
#:
#: `delta` is a signed count of ITEMS (+5 for a five-pack), so summing it gives units sold
#: and not revenue. Both purchase paths — the browser callback at billing.py:481 and the
#: webhook at billing.py:617 — write `detail.amount_paise`, which is what Razorpay actually
#: captured. A 100%-off code writes KIND_GRANT with `charged_paise: 0` instead, so free
#: product is excluded here by construction rather than by a filter somebody has to remember.
#:
#: DEDUPED PER PAYMENT, NOT PER ROW. `payment_ref` is indexed but NOT unique, and two
#: independent paths can grant one payment — the webhook and the browser callback each check
#: the ledger before inserting, but that check is a read-then-write with a window in it.
#: Counting rows would turn a double-grant into double revenue, which is the direction that
#: flatters us; `DISTINCT ON` makes the figure robust to it. `coalesce(payment_ref, id::text)`
#: is the dedup key so a purchase with no payment reference still counts exactly once rather
#: than collapsing every such row into one.
_REVENUE_ROWS = """
    SELECT DISTINCT ON (coalesce(payment_ref, id::text))
           coalesce((detail->>'amount_paise')::bigint, 0) AS paise,
           created_at,
           detail->>'item_id'                             AS item_id,
           user_id
      FROM credit_events
     WHERE kind = 'purchase'
       AND created_at >= :since
     ORDER BY coalesce(payment_ref, id::text), created_at
"""


@router.get("/revenue", summary="What the product actually took, per payment")
async def admin_revenue(
    current_user: AdminUser,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    Gross revenue over a window, by day and by item.

    GROSS, AND SAID SO. This is what was captured, before Razorpay's fee and before any
    refund — neither of which this system records, so calling it "net" would be a guess
    dressed as a figure. The number is comparable to the Razorpay dashboard's captured
    total; it is not a P&L.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (await db.execute(text(_REVENUE_ROWS), {"since": since})).all()

    gross_paise = sum(int(r.paise) for r in rows)
    payments = len(rows)
    paying_users = len({r.user_id for r in rows if r.user_id is not None})

    by_day: dict[str, dict] = {}
    for r in rows:
        key = r.created_at.date().isoformat()
        bucket = by_day.setdefault(key, {"day": key, "paise": 0, "payments": 0})
        bucket["paise"] += int(r.paise)
        bucket["payments"] += 1
    for bucket in by_day.values():
        bucket["inr"] = _inr(bucket["paise"])

    by_item: dict[str, dict] = {}
    for r in rows:
        # An item id that is no longer in the catalogue still has to appear, or historic
        # revenue silently vanishes the moment a product is renamed or retired.
        item_id = r.item_id or "unknown"
        bucket = by_item.setdefault(
            item_id, {"item_id": item_id, "name": "", "paise": 0, "payments": 0}
        )
        bucket["paise"] += int(r.paise)
        bucket["payments"] += 1
    for item_id, bucket in by_item.items():
        item = get_item(item_id)
        bucket["name"] = item.name if item else f"{item_id} (retired)"
        bucket["inr"] = _inr(bucket["paise"])

    # Product given away: 100%-off codes and support goodwill. Not revenue, but the figure
    # that makes revenue legible — a flat month with a spike here is a promotion working,
    # not demand collapsing.
    granted = await db.scalar(
        text(
            "SELECT count(*) FROM credit_events "
            "WHERE kind = 'grant' AND created_at >= :since"
        ),
        {"since": since},
    )

    all_time_paise = await db.scalar(
        text(
            "SELECT coalesce(sum(paise), 0) FROM ("
            "  SELECT DISTINCT ON (coalesce(payment_ref, id::text)) "
            "         coalesce((detail->>'amount_paise')::bigint, 0) AS paise"
            "    FROM credit_events WHERE kind = 'purchase'"
            "   ORDER BY coalesce(payment_ref, id::text), created_at"
            ") t"
        )
    )

    return {
        "window_days": days,
        "since": since.isoformat(),
        "gross_paise": gross_paise,
        "gross_inr": _inr(gross_paise),
        "payments": payments,
        "paying_users": paying_users,
        # Integer division so the average is itself a real paise value rather than a float
        # that renders as ₹49.000000000000004.
        "average_order_paise": gross_paise // payments if payments else 0,
        "average_order_inr": _inr(gross_paise // payments) if payments else 0.0,
        "free_grants": int(granted or 0),
        "all_time_gross_paise": int(all_time_paise or 0),
        "all_time_gross_inr": _inr(int(all_time_paise or 0)),
        "by_day": sorted(by_day.values(), key=lambda b: b["day"]),
        "by_item": sorted(by_item.values(), key=lambda b: b["paise"], reverse=True),
    }


# ─── Marketing list ───────────────────────────────────────────────────────────
#
# "i want the activity and what is left in each user id as the information for me to mail
# them for marketing."
#
# WHAT THIS IS FOR, BECAUSE IT DECIDES WHAT IS IN IT. The owner writes the emails himself,
# by hand, to a few hundred campus students at a time. So this is not an analytics screen —
# it is the input to a mail merge. Every column below exists because it changes the sentence
# he would write to that person, and anything that does not was left out:
#
#   * WHAT IS LEFT (per feature) — "you still have a free interview waiting" is a different
#     email from "your free interview is used up, here is what one more costs", and sending
#     the wrong one of those two is the fastest way to be unsubscribed.
#   * SESSIONS STARTED vs COMPLETED — somebody who started and never finished is the largest
#     recoverable group there is, and they need "come back and finish", not an offer.
#   * WHETHER A REPORT EXISTS — with the drive report paywall live, "you sat the interview
#     and your personalised report is ready" is the single highest-intent email in the
#     product. It is only true of people who have a report.
#   * WHETHER THEY HAVE EVER PAID — a customer gets thanked and told what is next; a
#     non-customer gets an offer. Mixing those up insults both.
#   * LAST ACTIVITY — nobody mails a list without knowing who has gone cold.
#
# WHAT IS DELIBERATELY NOT HERE. No rupee total per user: that would be a second revenue
# figure computed a second way, and `/admin/revenue` is the one that reconciles with the
# Razorpay dashboard — two numbers for one question is how neither gets trusted. No content
# of any kind: not an answer, not a transcript, not a report, not a score, not an IP. This
# endpoint returns COUNTS AND FLAGS about accounts the admin screen already lists by email,
# and nothing about what anybody said in an interview. That boundary is asserted by
# `test_admin_marketing.py::TestNoNewDisclosure`, which pins the exact key set of a row so
# that widening it has to be a deliberate act rather than a convenient one.
#
# WHY IT IS A SEPARATE ENDPOINT FROM /users RATHER THAN SIX MORE COLUMNS ON IT. /users is
# the access-control screen — it exists to deactivate somebody and to grant admin, and it is
# already a wide table. These are different questions asked at a different time, and the
# export below has to cover everybody at once rather than the page you happen to be on.
# The two share every rule they have in common by calling the same helpers.


#: The whole list, in one response, up to this many accounts.
#:
#: NOT PAGINATED, AND THAT IS THE POINT. The list is destined for a mail merge, so the export
#: has to be the whole thing; a paginated table plus a "download" that silently covered only
#: page one would be worse than no export at all. Serving every row once and letting the
#: browser search, filter and write the CSV from exactly the rows it is showing means there
#: is one set of rows and no way for the table and the file to disagree.
#:
#: The cap is a bound on a response, not a product limit: at the size this product is (a few
#: hundred accounts) it is never reached, and if it ever is, `truncated` says so out loud and
#: names how many were left off rather than quietly shortening the list. Truncation keeps the
#: NEWEST accounts, because a list this size is being mailed about a drive that is imminent.
_MARKETING_MAX_ROWS = 2000


#: One export is one page load. A limit here is not about cost — the queries are five grouped
#: aggregates — it is that this is the only endpoint in the product that returns every
#: candidate's email address in one response, so an authenticated admin token in a loop (or a
#: stolen one) should not be able to pull the whole user base repeatedly without tripping.
#: Its own Redis bucket, derived from the admin namespace, so it cannot eat the budget that
#: the deactivate button needs in an incident.
_marketing_read_rate_limit = rate_limiter(
    limit=20,
    window_seconds=60,
    key_builder=lambda user_id: f"{CacheKeys.rate_limit_admin(user_id)}:marketing",
    action="reading the marketing list",
)


class MarketingRow(BaseModel):
    """
    One account, as much as is needed to write it an email and no more.

    `remaining` is keyed by feature id; the labels and the column order come from
    `MarketingListResponse.features` so the browser never hard-codes either.
    """

    user_id: uuid.UUID
    email: str
    full_name: str | None
    joined_at: datetime
    is_active: bool
    is_admin: bool
    #: Operator account: not metered at all, so `remaining` is meaningless for it. Surfaced
    #: as a flag rather than as a big number for the same reason `credits.Balance` does it —
    #: "2 interviews left" quoted at your own admin in a marketing email is embarrassing,
    #: and a countdown that never moves looks like a broken meter.
    unlimited: bool
    #: feature id → how many of it this account may still start. See `_remaining_by_user`.
    remaining: dict[str, int]
    #: INTERVIEW sessions, which is what the `sessions` column on `/admin/users` counts too.
    #: Group discussions and communication drills live in their own tables and are deliberately
    #: not folded in here: one number covering three different products would make the
    #: started-versus-completed pair meaningless, and the two admin screens would then disagree
    #: about how many sessions the same person has had. What is left of the other two features
    #: is in `remaining`, which is where entitlement questions belong.
    sessions_started: int
    sessions_completed: int
    #: Reports that exist for this account. A report is the thing the drive paywall sells, so
    #: "has one" and "has none" are two different emails.
    reports: int
    #: The most recent of: a session, a report, a ledger entry. None means they have done
    #: nothing at all since signing up, which is itself a segment.
    last_active_at: datetime | None
    ever_paid: bool
    last_paid_at: datetime | None
    #: One of `_SEGMENTS`. Exactly one per row — see `_segment_of`.
    segment: str


class MarketingSegment(BaseModel):
    segment: str
    label: str
    #: What to say to this group. Copy, not configuration — it is here so the legend in the
    #: UI and the reasoning in this file cannot drift apart.
    pitch: str
    count: int


class MarketingFeature(BaseModel):
    feature: str
    label: str


class MarketingListResponse(BaseModel):
    generated_at: datetime
    #: Every account matching the filters, before the cap.
    total: int
    returned: int
    #: True when `total` exceeded `_MARKETING_MAX_ROWS` and the oldest accounts were left off.
    truncated: bool
    features: list[MarketingFeature]
    segments: list[MarketingSegment]
    users: list[MarketingRow]


#: THE SEGMENTS, IN PRECEDENCE ORDER, AND THE ORDER IS THE DESIGN.
#:
#: A row gets exactly one segment because the point of the column is to answer "which of my
#: five emails does this person get". A row that matched three segments would need the owner
#: to break the tie by hand for every address, which is the work this column exists to remove.
#:
#: Precedence runs most-committed first, and each rule is written as "what is the truest thing
#: about this person today":
#:
#:   customer        — they have paid us money. That outranks everything else: whatever else
#:                     is true, you do not send an offer to somebody who has just bought.
#:   report_waiting  — a report exists and they have never paid. With the drive paywall live
#:                     this is the money segment: the work is done, the report is generated
#:                     and stored, and one ₹50 unlock stands between them and it.
#:   finished_no_report
#:                   — completed a session but no report exists. Something did not finish, or
#:                     they left before it generated. Support-shaped, not sales-shaped, and
#:                     mailing it an offer would be asking for money for a thing they cannot
#:                     see yet.
#:   dropped_off     — started at least one session, completed none. The biggest recoverable
#:                     group in any product like this, and the cheapest to recover: they have
#:                     already decided to try.
#:   never_started   — signed up and did nothing. Still holding their whole free trial, so
#:                     the email is "your free interview is still here", never a price.
#:
#: `pitch` is the one-line reason each group is being mailed, kept beside the rule rather than
#: in a document, because a segment whose purpose has been forgotten is a segment that quietly
#: starts receiving the wrong email.
_SEGMENTS: tuple[tuple[str, str, str], ...] = (
    ("customer", "Paid before", "Thank them, and tell them what is next."),
    (
        "report_waiting",
        "Report ready, unpaid",
        "Their personalised report is generated and locked — the ₹50 unlock.",
    ),
    (
        "finished_no_report",
        "Finished, no report",
        "Something did not complete. Ask what happened before selling anything.",
    ),
    ("dropped_off", "Started, never finished", "Come back and finish the interview you began."),
    ("never_started", "Signed up, never started", "Their free interview is still waiting."),
)


def _segment_of(row_ever_paid: bool, reports: int, completed: int, started: int) -> str:
    """
    The one segment this account belongs to.

    Pure, and takes only the four facts it needs, so the precedence documented on `_SEGMENTS`
    can be tested exhaustively without a database. Derived entirely from fields the row
    already carries, which is what makes it impossible for the segment to disagree with the
    columns beside it.
    """
    if row_ever_paid:
        return "customer"
    if reports > 0:
        return "report_waiting"
    if completed > 0:
        return "finished_no_report"
    if started > 0:
        return "dropped_off"
    return "never_started"


async def _remaining_by_user(
    db: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    """
    What every one of these accounts has left, per metered feature.

    THIS IS `credits.remaining_for`'S ARITHMETIC, NOT A SECOND OPINION. That function is
    `max(0, trial_allowance(feature) + SUM(delta))` over `credit_events` grouped by feature,
    and so is this, line for line — the trial numbers themselves come from
    `plans.trial_allowance`, so there is no second copy of an allowance anywhere. It is
    written out here for exactly one reason: `remaining_for` answers for ONE user, and
    calling it per row is the N+1 that turns this page into a timeout the week it has real
    accounts on it. This is the set-wide form of the same query — one grouped statement for
    the whole list, however long the list is.

    A NUMBER QUOTED AT A CUSTOMER MUST MATCH THE ONE ON THEIR DASHBOARD, so the agreement is
    not left to the two functions looking similar: `test_admin_marketing.py` runs both
    against the same real ledger rows and asserts they return the same integer for every
    user and every feature. If someone changes how entitlement is counted, that test fails
    here rather than an admin promising somebody an interview they do not have.

    The honest long-term home for this is a bulk function in `services/billing/credits.py`
    that `remaining_for` itself delegates to; that file is out of scope for this change, so
    the equivalence is pinned by test instead of by construction.

    Admins are not metered at all (`credits.consume` returns before it looks at any balance),
    so their numbers here are meaningless and the row carries `unlimited` to say so rather
    than a figure that would be quoted at them.
    """
    if not user_ids:
        return {}

    rows = (
        await db.execute(
            select(
                CreditEvent.user_id,
                CreditEvent.feature,
                func.coalesce(func.sum(CreditEvent.delta), 0),
            )
            .where(CreditEvent.user_id.in_(user_ids))
            .group_by(CreditEvent.user_id, CreditEvent.feature)
        )
    ).all()

    net: dict[uuid.UUID, dict[str, int]] = {}
    for uid, feature, total in rows:
        net.setdefault(uid, {})[feature] = int(total or 0)

    return {
        uid: {
            # Identical to credits.remaining_for: the trial is a constant added at read time,
            # never rows, and the sum is already net of consumption because `delta` is signed.
            feature: max(0, trial_allowance(feature) + net.get(uid, {}).get(feature, 0))
            for feature in FEATURES
        }
        for uid in user_ids
    }


async def _activity_by_user(
    db: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict]:
    """
    Sessions, reports and payment history for these accounts — three grouped queries, total.

    NOT ONE QUERY PER USER, and not a relationship load either. Per-user aggregates in a loop
    is precisely how an admin table with a few hundred rows on it starts timing out, and it
    does so gradually, so it reads as "the admin page is slow lately" rather than as a bug
    with a cause. Each statement below is one aggregate over one table for the whole list.

    `count(*) FILTER (WHERE ...)` rather than a second query for the completed count: the
    started/completed pair is only meaningful read together, and two queries could be answered
    either side of a session finishing, which would show more completions than starts.
    """
    if not user_ids:
        return {}

    out: dict[uuid.UUID, dict] = {
        uid: {
            "sessions_started": 0,
            "sessions_completed": 0,
            "last_session_at": None,
            "reports": 0,
            "last_report_at": None,
            "ledger_at": None,
            "purchases": 0,
            "last_paid_at": None,
        }
        for uid in user_ids
    }

    sessions = (
        await db.execute(
            select(
                InterviewSession.user_id,
                func.count(),
                func.count().filter(InterviewSession.status == SessionStatus.COMPLETED.value),
                func.max(InterviewSession.created_at),
            )
            .where(InterviewSession.user_id.in_(user_ids))
            .group_by(InterviewSession.user_id)
        )
    ).all()
    for uid, started, completed, last_at in sessions:
        out[uid]["sessions_started"] = int(started or 0)
        out[uid]["sessions_completed"] = int(completed or 0)
        out[uid]["last_session_at"] = last_at

    reports = (
        await db.execute(
            select(Report.user_id, func.count(), func.max(Report.created_at))
            .where(Report.user_id.in_(user_ids))
            .group_by(Report.user_id)
        )
    ).all()
    for uid, n, last_at in reports:
        out[uid]["reports"] = int(n or 0)
        out[uid]["last_report_at"] = last_at

    # WHY THE LEDGER IS READ FOR ACTIVITY AND NOT JUST FOR MONEY. `credit_events` is written
    # when somebody starts anything metered, so its latest row is a real activity timestamp —
    # and for a user whose sessions were deleted it may be the only one left.
    #
    # PAYMENT IS A COUNT OF `purchase` ROWS, NOT A SUM OF ANYTHING. Deliberately: a boolean
    # ("have they ever paid") and a MAX ("when") are both immune to the double-grant that
    # `/admin/revenue` has to dedupe against with DISTINCT ON, because counting one payment
    # twice cannot change either answer. That is why this can read the ledger directly
    # without carrying a copy of the revenue query's dedup rule around. `grant` rows are
    # excluded on purpose — a 100%-off code and support goodwill are product given away, and
    # somebody who has never actually paid must not be mailed as a customer.
    ledger = (
        await db.execute(
            select(
                CreditEvent.user_id,
                func.max(CreditEvent.created_at),
                func.count().filter(CreditEvent.kind == KIND_PURCHASE),
                func.max(CreditEvent.created_at).filter(CreditEvent.kind == KIND_PURCHASE),
            )
            .where(CreditEvent.user_id.in_(user_ids))
            .group_by(CreditEvent.user_id)
        )
    ).all()
    for uid, last_at, purchases, last_paid in ledger:
        out[uid]["ledger_at"] = last_at
        out[uid]["purchases"] = int(purchases or 0)
        out[uid]["last_paid_at"] = last_paid

    return out


def _latest(*values: datetime | None) -> datetime | None:
    """
    The most recent of several timestamps, ignoring the missing ones.

    Written out rather than `max(filter(None, ...))` because these come from three different
    tables and any of them can be NULL, and `max()` over an empty sequence raises — on an
    account that has done nothing, which is the commonest row in a marketing list.
    """
    known = [v for v in values if v is not None]
    return max(known) if known else None


@router.get(
    "/marketing",
    response_model=MarketingListResponse,
    summary="Per-account activity and remaining entitlement, for mailing",
    dependencies=[Depends(_marketing_read_rate_limit)],
)
async def marketing_list(
    current_user: AdminUser,
    q: str | None = Query(None, max_length=200, description="Match on email or name."),
    active: bool | None = Query(None, description="Filter by account state."),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> MarketingListResponse:
    """
    Everybody, what they have left, what they have done, and which email they should get.

    ADMIN ONLY, THROUGH THE SAME GUARD AS EVERY OTHER ROUTE IN THIS FILE. `AdminUser` is the
    dependency, so a non-admin gets a 403 before a line of this function runs and a
    deactivated admin gets one before that — `get_current_admin_user` depends on
    `get_current_user`, which is where `is_active` is enforced. This is the one endpoint that
    returns every candidate's email address in a single response, so it gets no exceptions to
    that and its own rate-limit bucket.

    `q` and `active` are the same two filters, with the same names and the same meaning, as
    `GET /admin/users`. Same rule, same spelling, so an admin who has learned one screen has
    learned this one.
    """
    # Accounts first, newest signups first. The aggregates below are keyed off exactly this
    # set of ids, so the whole response is constant in the number of queries however many
    # accounts come back.
    stmt = (
        select(User.id, User.email, User.is_active, User.is_admin, User.created_at, Profile.full_name)
        .outerjoin(Profile, Profile.user_id == User.id)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), Profile.full_name.ilike(like)))
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0

    rows = (
        await db.execute(stmt.order_by(User.created_at.desc()).limit(_MARKETING_MAX_ROWS))
    ).all()
    ids = [r.id for r in rows]

    remaining = await _remaining_by_user(db, ids)
    activity = await _activity_by_user(db, ids)

    users: list[MarketingRow] = []
    for r in rows:
        a = activity.get(r.id, {})
        ever_paid = int(a.get("purchases") or 0) > 0
        users.append(
            MarketingRow(
                user_id=r.id,
                email=r.email,
                full_name=r.full_name,
                joined_at=r.created_at,
                is_active=r.is_active,
                is_admin=r.is_admin,
                unlimited=r.is_admin,
                remaining=remaining.get(r.id, {f: trial_allowance(f) for f in FEATURES}),
                sessions_started=int(a.get("sessions_started") or 0),
                sessions_completed=int(a.get("sessions_completed") or 0),
                reports=int(a.get("reports") or 0),
                last_active_at=_latest(
                    a.get("last_session_at"), a.get("last_report_at"), a.get("ledger_at")
                ),
                ever_paid=ever_paid,
                last_paid_at=a.get("last_paid_at"),
                segment=_segment_of(
                    ever_paid,
                    int(a.get("reports") or 0),
                    int(a.get("sessions_completed") or 0),
                    int(a.get("sessions_started") or 0),
                ),
            )
        )

    # Most recently active first, and never-active last rather than first. This is the order
    # somebody mails in: the person who was here yesterday is the person most likely to open
    # it. Sorted here rather than in SQL because "last active" is the latest of three
    # different tables' timestamps, and ordering on that in the database would mean joining
    # all three into the paging query for a list that is already bounded and in memory.
    users.sort(key=lambda u: (u.last_active_at is not None, u.last_active_at or u.joined_at), reverse=True)

    counts = {seg: 0 for seg, _label, _pitch in _SEGMENTS}
    for u in users:
        counts[u.segment] = counts.get(u.segment, 0) + 1

    logger.info(
        # Not an `audit_logs` row, deliberately. That table's admin slice is what
        # `GET /admin/audit` renders, and it exists to make access changes easy to find; one
        # entry per page load of this screen would bury them, which is the exact failure that
        # endpoint's docstring warns about. Who pulled the list is recorded here instead, with
        # the same actor id and a count, where an operational question can be answered without
        # drowning the access trail.
        "admin_marketing_list_read",
        actor=str(current_user.user_id),
        returned=len(users),
        total=total,
    )

    return MarketingListResponse(
        generated_at=datetime.now(UTC),
        total=total,
        returned=len(users),
        truncated=total > len(users),
        # The browser renders the columns the server names, in this order, with these labels.
        # `FEATURE_LABELS` is the product's own copy for these features — the same dict the
        # 402 paywall message is built from — so a feature cannot be called one thing to a
        # candidate and another to the person mailing them.
        features=[MarketingFeature(feature=f, label=FEATURE_LABELS.get(f, f)) for f in FEATURES],
        segments=[
            MarketingSegment(segment=seg, label=label, pitch=pitch, count=counts.get(seg, 0))
            for seg, label, pitch in _SEGMENTS
        ],
        users=users,
    )
