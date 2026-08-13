"""
API v1 Router — api/v1/router.py

Assembles all v1 endpoint routers into one unified router.
This is the only file that needs to change when adding a new endpoint group.
"""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    admin_offers,
    ai_usage,  # TEMPORARY — token counter
    analysis,
    auth,
    billing,
    code,
    communication,
    companies,
    gd,
    health,
    interview,
    panel,
    progress,
    questions,
    quiz,
    reports,
    resume,
    tts,
    users,
)

v1_router = APIRouter()

# No auth required
v1_router.include_router(health.router, prefix="/health", tags=["Health"])
v1_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
# Billing: /plans is public (a pricing page behind a login loses the sale) and
# /webhook is authenticated by Razorpay's HMAC rather than by a user token. The
# remaining routes take CurrentUser individually.
v1_router.include_router(billing.router, tags=["Billing"])
# Prefixed inside the module, so it lands under /admin/offers alongside the rest of the
# admin surface rather than under a second top-level path.
v1_router.include_router(admin_offers.router, tags=["Admin — Offers"])

# Auth required
v1_router.include_router(users.router, prefix="/users", tags=["Users"])
v1_router.include_router(questions.router, prefix="/questions", tags=["Questions"])
v1_router.include_router(companies.router, prefix="/companies", tags=["Campus Recruiters"])
v1_router.include_router(interview.router, prefix="/interview", tags=["Interview"])
v1_router.include_router(quiz.router, prefix="/quiz", tags=["Quiz"])
v1_router.include_router(communication.router, prefix="/communication", tags=["Communication"])
v1_router.include_router(gd.router, prefix="/gd", tags=["Group Discussion"])
v1_router.include_router(code.router, prefix="/code", tags=["Code Execution"])
v1_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
v1_router.include_router(panel.router, tags=["Interview Panel"])
v1_router.include_router(progress.router, tags=["Progress"])
v1_router.include_router(tts.router, tags=["Speech"])
v1_router.include_router(analysis.router, prefix="/analysis", tags=["Detailed Analysis"])
v1_router.include_router(resume.router, prefix="/resume", tags=["Resume"])

# Admin only — user management, per-user usage, activation. Every route is
# gated by the AdminUser dependency (users.is_admin).
v1_router.include_router(admin.router, tags=["Admin"])

# TEMPORARY — per-feature AI cost breakdown, admin only. Removed with the rest
# of the ledger once credits ship; see docs/TEMPORARY-token-counter.md.
v1_router.include_router(ai_usage.router, tags=["AI usage (temporary)"])
