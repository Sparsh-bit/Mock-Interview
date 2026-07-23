"""
Health Check Endpoint — api/v1/health.py
GET /api/v1/health
"""

from __future__ import annotations

from fastapi import APIRouter

from app.db.redis import check_redis_connection
from app.db.session import check_db_connection

router = APIRouter()


@router.get("", summary="Service health check")
async def health_check():
    """
    Returns the operational status of all infrastructure dependencies.
    Used by load balancers, monitoring systems, and the frontend status page.

    Response codes:
      200 — Application running (even if dependencies are degraded)
      Use the individual status fields to detect partial failures.
    """
    db_ok = await check_db_connection()
    redis_ok = await check_redis_connection()
    supabase_ok = await _check_supabase_connection()

    return {
        "status": "ok",
        "database": "connected" if db_ok else "unreachable",
        "redis": "connected" if redis_ok else "unreachable",
        "supabase": "connected" if supabase_ok else "unreachable",
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
