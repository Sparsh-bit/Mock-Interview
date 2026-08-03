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

THE COST COLUMN IS TEMPORARY DATA IN A PERMANENT PAGE. Per-user spend is read
from `ai_usage`, which is scheduled for deletion once credits ship — see
TEMPORARY-token-counter.md. The queries degrade to zero rather than failing when
that table is gone, so removing the ledger does not break this page; the column
just needs repointing at whatever billing records instead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import AdminUser
from app.db.redis import CacheKeys
from app.db.session import get_db
from app.models.session import InterviewSession
from app.models.system import AuditLog
from app.models.user import Profile, User

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
