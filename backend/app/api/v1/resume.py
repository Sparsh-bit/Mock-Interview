"""
Resume Upload Endpoints — api/v1/resume.py

POST   /api/v1/resume/upload        — Upload resume PDF/DOCX
GET    /api/v1/resume/               — List user's resumes
DELETE /api/v1/resume/{id}          — Delete a resume
PATCH  /api/v1/resume/{id}/primary  — Set as primary resume
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import settings
from app.core.security import CurrentUser
from app.db.session import AsyncSession, get_db
from app.events import (
    ResumeUploadedEvent,
    ResumeUploadedPayload,
    get_event_emitter,
)
from app.events.emitter import EventEmitter

logger = structlog.get_logger(__name__)
router = APIRouter()

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}


class ResumeResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_size_bytes: int
    mime_type: str
    is_primary: bool
    parsing_status: str
    parsed_skills: list[str] | None
    created_at: datetime


@router.post(
    "/upload",
    response_model=ResumeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_resume(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    emitter: EventEmitter = Depends(get_event_emitter),
    file: UploadFile = File(...),
):
    """
    Upload a resume file for interview personalization.

    Accepted formats: PDF, DOCX
    Max size: 10 MB (configurable via MAX_UPLOAD_SIZE_MB)

    Phase 6 implements AI resume parsing. This endpoint stores the file
    and creates the database record with parsing_status="pending".
    """
    from app.models.report import ResumeFile  # noqa: PLC0415

    # Validate file type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}. Accepted: PDF, DOCX",
        )

    # Read file and check size
    file_bytes = await file.read()
    file_size = len(file_bytes)

    if file_size > settings.upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed: {settings.MAX_UPLOAD_SIZE_MB} MB",
        )

    # Upload to Supabase Storage
    from supabase import create_client  # noqa: PLC0415

    file_id = uuid.uuid4()
    supabase = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_KEY,
    )

    storage_path = f"resumes/{current_user.user_id}/{file_id}/{file.filename}"
    supabase.storage.from_(settings.SUPABASE_STORAGE_BUCKET_RESUMES).upload(
        storage_path,
        file_bytes,
        {"content-type": file.content_type or "application/pdf"},
    )

    # Create database record
    resume = ResumeFile(
        id=file_id,
        user_id=current_user.user_id,
        filename=file.filename or "resume",
        storage_path=storage_path,
        file_size_bytes=file_size,
        mime_type=file.content_type or "application/pdf",
        is_primary=False,
        parsing_status="pending",
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    # Emit event
    await emitter.emit(
        ResumeUploadedEvent(
            user_id=current_user.user_id,
            payload=ResumeUploadedPayload(
                resume_file_id=resume.id,
                filename=resume.filename,
                file_size_bytes=file_size,
                mime_type=resume.mime_type,
            ),
        )
    )

    logger.info(
        "resume_uploaded",
        resume_id=str(resume.id),
        user_id=str(current_user.user_id),
        filename=file.filename,
        size_bytes=file_size,
    )

    return ResumeResponse(
        id=resume.id,
        filename=resume.filename,
        file_size_bytes=resume.file_size_bytes,
        mime_type=resume.mime_type,
        is_primary=resume.is_primary,
        parsing_status=resume.parsing_status,
        parsed_skills=resume.parsed_skills,
        created_at=resume.created_at,
    )


@router.get("/", response_model=list[ResumeResponse])
async def list_resumes(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    from app.models.report import ResumeFile  # noqa: PLC0415

    result = await db.execute(
        select(ResumeFile)
        .where(ResumeFile.user_id == current_user.user_id)
        .order_by(ResumeFile.created_at.desc())
    )
    resumes = result.scalars().all()

    return [
        ResumeResponse(
            id=r.id,
            filename=r.filename,
            file_size_bytes=r.file_size_bytes,
            mime_type=r.mime_type,
            is_primary=r.is_primary,
            parsing_status=r.parsing_status,
            parsed_skills=r.parsed_skills,
            created_at=r.created_at,
        )
        for r in resumes
    ]


@router.patch("/{resume_id}/primary")
async def set_primary(
    resume_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    from app.models.report import ResumeFile  # noqa: PLC0415
    from sqlalchemy import update  # noqa: PLC0415

    # Verify ownership
    result = await db.execute(
        select(ResumeFile).where(
            ResumeFile.id == resume_id,
            ResumeFile.user_id == current_user.user_id,
        )
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Clear existing primary
    await db.execute(
        update(ResumeFile)
        .where(ResumeFile.user_id == current_user.user_id)
        .values(is_primary=False)
    )
    resume.is_primary = True
    await db.commit()

    return {"resume_id": str(resume_id), "is_primary": True}


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    from app.models.report import ResumeFile  # noqa: PLC0415
    from supabase import create_client  # noqa: PLC0415

    result = await db.execute(
        select(ResumeFile).where(
            ResumeFile.id == resume_id,
            ResumeFile.user_id == current_user.user_id,
        )
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Delete from Supabase Storage
    supabase = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_KEY,
    )
    try:
        supabase.storage.from_(settings.SUPABASE_STORAGE_BUCKET_RESUMES).remove([resume.storage_path])
    except Exception:
        logger.exception("supabase_storage_delete_failed", path=resume.storage_path)

    await db.delete(resume)

    logger.info("resume_deleted", resume_id=str(resume_id))
