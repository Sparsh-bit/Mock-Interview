import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.core.security import CurrentUser
from app.models.session import InterviewSession
from app.services.interview.orchestrator import InterviewOrchestrator
from pydantic import BaseModel

router = APIRouter()


async def _verify_session_ownership(
    db: AsyncSession, session_id: uuid.UUID, current_user: CurrentUser
) -> None:
    """Ensure the session belongs to the current user, else 404."""
    result = await db.execute(
        select(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.user_id == current_user.user_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Session not found")

class StartSessionRequest(BaseModel):
    track_id: uuid.UUID

class SubmitAnswerRequest(BaseModel):
    question_id: uuid.UUID
    content: str

@router.post("/start", status_code=status.HTTP_201_CREATED)
async def start_interview_session(
    request: StartSessionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    orchestrator = InterviewOrchestrator(db)
    session = await orchestrator.start_session(current_user.user_id, request.track_id)
    return {"session_id": session.id, "status": session.status}

@router.get("/{session_id}/next")
async def get_next_question(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _verify_session_ownership(db, session_id, current_user)
    orchestrator = InterviewOrchestrator(db)
    question = await orchestrator.get_next_question(session_id)
    if not question:
        return {"question": None, "message": "Session complete or no questions available."}
    return {
        "question": {
            "id": question.id,
            "content": question.content,
            "type": question.type,
            "difficulty": question.difficulty
        }
    }

@router.post("/{session_id}/answer")
async def submit_answer(
    session_id: uuid.UUID,
    request: SubmitAnswerRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _verify_session_ownership(db, session_id, current_user)
    orchestrator = InterviewOrchestrator(db)
    result = await orchestrator.submit_answer(session_id, request.question_id, request.content)
    return result

@router.post("/{session_id}/complete")
async def complete_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _verify_session_ownership(db, session_id, current_user)
    orchestrator = InterviewOrchestrator(db)
    await orchestrator.complete_session(session_id)
    return {"message": "Session completed"}
