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
docs/TEMPORARY-token-counter.md. The queries degrade to zero rather than failing when
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
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import AdminUser
from app.db.redis import CacheKeys
from app.db.session import get_db
from app.models.session import InterviewSession
from app.models.system import AuditLog
from app.models.user import Profile, User
from app.services.billing.plans import get_item

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


# ─── Credential-sharing bans ──────────────────────────────────────────────────


class UnbanRequest(BaseModel):
    #: Why the ban is being lifted. Required, because "unbanned" with no reason is
    #: indistinguishable from a misclick when the same account is reviewed again later.
    note: str = Field(min_length=3, max_length=300)


@router.get("/bans", summary="Suspended accounts, appeals first")
async def list_bans(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[dict]:
    """
    The review queue.

    ORDERED WITH APPEALS FIRST because that is the actionable half. A ban nobody has
    appealed needs no decision today; a person who has written in is waiting, and the
    detector has a real false-positive rate — mobile handover, campus NAT, dual-stack
    flapping — so somebody is waiting who should not be banned at all.
    """
    from app.models.billing import UserPlan  # noqa: PLC0415
    from app.services.security.sharing import recent_places  # noqa: PLC0415

    rows = (
        await db.execute(
            select(UserPlan, User.email)
            .join(User, User.id == UserPlan.user_id)
            .where(UserPlan.is_banned.is_(True))
            .order_by(UserPlan.appeal_at.desc().nullslast(), UserPlan.banned_at.desc())
            .limit(200)
        )
    ).all()

    out = []
    for plan, email in rows:
        out.append(
            {
                "user_id": str(plan.user_id),
                "email": email,
                "reason": plan.ban_reason,
                "banned_at": plan.banned_at.isoformat() if plan.banned_at else None,
                "appeal_text": plan.appeal_text,
                "appeal_at": plan.appeal_at.isoformat() if plan.appeal_at else None,
                # Repeat offenders are the ones where a second unban needs more thought.
                "previously_unbanned": plan.unbanned_count,
                # The evidence, so the decision is made against what actually happened
                # rather than against the one-line reason string.
                "places": await recent_places(db, plan.user_id),
            }
        )
    return out


@router.post(
    "/users/{user_id}/unban",
    summary="Lift a credential-sharing suspension",
    dependencies=[Depends(_admin_write_rate_limit)],
)
async def unban_user(
    user_id: uuid.UUID,
    body: UnbanRequest,
    current_user: AdminUser,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """
    ADMIN ONLY, AND THE ONLY WAY OUT. The appeal endpoint records a request; it deliberately
    cannot lift a ban, because a ban that clears itself on request is decorative.

    Clearing the strike counter is not optional. Strikes live in Redis with a week's TTL, so
    an account unbanned without clearing them is one overlap away from being banned again by
    evidence an admin has already reviewed and forgiven — which would look, correctly, like
    the unban button does not work.
    """
    from app.db.redis import get_redis  # noqa: PLC0415
    from app.models.billing import UserPlan  # noqa: PLC0415
    from app.services.security.sharing import clear_strikes  # noqa: PLC0415

    plan = await db.scalar(
        select(UserPlan).where(UserPlan.user_id == user_id).with_for_update()
    )
    if plan is None or not plan.is_banned:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account is not banned")

    reason_before = plan.ban_reason
    plan.is_banned = False
    plan.ban_reason = None
    plan.banned_at = None
    plan.appeal_text = None
    plan.appeal_at = None
    # Kept across the unban, unlike everything else above — it is the only signal that this
    # account has been here before.
    plan.unbanned_count = (plan.unbanned_count or 0) + 1

    await clear_strikes(get_redis(), user_id)

    db.add(
        AuditLog(
            user_id=current_user.user_id,
            action="admin.user_unbanned",
            entity_type="user",
            entity_id=user_id,
            ip_address=(request.client.host if request.client else None),
            user_agent=request.headers.get("user-agent"),
            payload={
                "actor_email": current_user.email,
                "note": body.note,
                "ban_reason": reason_before,
                "times_unbanned": plan.unbanned_count,
            },
        )
    )
    await db.commit()

    logger.info(
        "admin_user_unbanned",
        actor=str(current_user.user_id),
        target=str(user_id),
        times=plan.unbanned_count,
    )
    return {"status": "unbanned", "times_unbanned": plan.unbanned_count}


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
