"""
Health Check Endpoint — api/v1/health.py
GET /api/v1/health
"""

from __future__ import annotations

from fastapi import APIRouter

from app.db.redis import check_redis_connection
from app.db.session import check_db_connection
from app.services.ai.reachability import check_provider_chain

router = APIRouter()


@router.get("", summary="Service health check")
async def health_check():
    """
    Returns the operational status of all infrastructure dependencies.
    Used by load balancers, monitoring systems, and the frontend status page.

    Response codes:
      200 — Application running (even if dependencies are degraded)
      Use the individual status fields to detect partial failures.

    ALWAYS 200, INCLUDING WHEN THE DATABASE IS DOWN. This is deliberate — reporting
    each dependency in the body lets a load balancer keep a degraded-but-serving
    instance in rotation — and it is why every monitor in docs/UPTIME.md asserts on
    the BODY. A status-code-only check shows a green tick through a total outage.

    THE WHOLE HANDLER IS TIME-BOUNDED. Each probe below has its own timeout and the
    provider check has two, so a slow third party cannot make this endpoint slow. A
    health check that hangs is worse than one that reports a failure: the monitor
    times out and reports the entire service down because somebody else was having a
    bad minute.
    """
    db_ok = await check_db_connection()
    redis_ok = await check_redis_connection()
    supabase_ok = await _check_supabase_connection()
    providers = await check_provider_chain()

    return {
        "status": "ok",
        "database": "connected" if db_ok else "unreachable",
        "redis": "connected" if redis_ok else "unreachable",
        "supabase": "connected" if supabase_ok else "unreachable",
        # Per provider, so a reader can tell "the primary is down and we are on the
        # fallback" from "nothing works". `not_configured` when AI_PROVIDER names
        # nothing with a key — which is not a healthy deployment, and saying "ok"
        # about it would be the kind of green tick docs/UPTIME.md is about.
        "ai_providers": providers or "not_configured",
        # ═══════════════════════════════════════════════════════════════════
        # `ai_providers` IS DELIBERATELY *NOT* IN `dependencies_healthy`.
        #
        # That field is what docs/UPTIME.md pages somebody on, and the three
        # dependencies in it share a property the model providers do not: if any of
        # them is down, this service cannot serve. A model provider being
        # unreachable is a DEGRADATION — quizzes, reports already generated, the
        # dashboard, sign-in and payment all keep working, and the provider chain
        # falls back to the standby on its own.
        #
        # Folding it in would also make the alert fire on somebody else's incident
        # at 3 a.m. for something the fallback already handled. And "unknown" — a
        # slow probe — would read as an outage, which is exactly the false alarm
        # that gets a pager muted.
        #
        # It is reported so a human can see it. It is not wired to the alarm.
        # ═══════════════════════════════════════════════════════════════════
        "dependencies_healthy": db_ok and redis_ok and supabase_ok,
    }


async def _check_supabase_connection() -> bool:
    """
    Verify Supabase is reachable by calling the health endpoint.
    Never raises — returns False on failure.
    """
    try:
        import httpx  # noqa: PLC0415

        from app.core.config import settings  # noqa: PLC0415

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.SUPABASE_URL}/health",
                headers={"apikey": settings.SUPABASE_ANON_KEY},
            )
            return response.status_code == 200
    except Exception:
        return False
