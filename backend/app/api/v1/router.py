"""
API v1 Router — api/v1/router.py

Assembles all v1 endpoint routers into one unified router.
This is the only file that needs to change when adding a new endpoint group.
"""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    code,
    communication,
    health,
    interview,
    questions,
    quiz,
    reports,
    resume,
    users,
)

v1_router = APIRouter()

# No auth required
v1_router.include_router(health.router, prefix="/health", tags=["Health"])
v1_router.include_router(auth.router, prefix="/auth", tags=["Auth"])

# Auth required
v1_router.include_router(users.router, prefix="/users", tags=["Users"])
v1_router.include_router(questions.router, prefix="/questions", tags=["Questions"])
v1_router.include_router(interview.router, prefix="/interview", tags=["Interview"])
v1_router.include_router(quiz.router, prefix="/quiz", tags=["Quiz"])
v1_router.include_router(communication.router, prefix="/communication", tags=["Communication"])
v1_router.include_router(code.router, prefix="/code", tags=["Code Execution"])
v1_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
v1_router.include_router(resume.router, prefix="/resume", tags=["Resume"])
