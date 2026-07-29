"""
Resume Upload Endpoints — api/v1/resume.py

POST   /api/v1/resume/upload        — Upload resume PDF/DOCX
GET    /api/v1/resume/               — List user's resumes
DELETE /api/v1/resume/{id}          — Delete a resume
PATCH  /api/v1/resume/{id}/primary  — Set as primary resume
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select, update

from app.core.config import settings
from app.core.security import CurrentUser
from app.db.session import AsyncSession, get_db
from app.events import (
    ResumeUploadedEvent,
    ResumeUploadedPayload,
    get_event_emitter,
)
from app.events.emitter import EventEmitter
from app.services.ai.schemas import ResumeAnalysisResponse
from app.services.resume import (
    ResumeExtractionError,
    extract_text,
    looks_like_a_resume,
)
from app.services.resume.analyser import analyse_resume

logger = structlog.get_logger(__name__)
router = APIRouter()

#: Wall-clock ceiling on resume analysis at upload time.
#:
#: Sized to sit well inside a managed host's ~100s gateway cut even from a cold
#: start, because a gateway 502 carries no CORS headers and reaches the browser as
#: an opaque CORS error rather than a timeout. Exceeding it is not a failure: the
#: extracted text is stored regardless, so the interview is still personalised.
_RESUME_ANALYSIS_BUDGET_SECONDS = 45.0

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
    #: "completed" | "text_only" | "failed" | "pending"
    parsing_status: str
    parsed_skills: list[str] | None
    created_at: datetime
    #: Candidate-facing explanation when analysis did not fully succeed.
    parsing_error: str | None = None
    #: Whether readable text was extracted. This, not parsing_status, is what
    #: decides if an interview can be personalised at all.
    has_text: bool = False
    #: Counts rather than full payloads: the UI shows "14 skills · 4 projects"
    #: and the interviewer reads the detail server-side, so shipping the whole
    #: analysis to the browser on every profile load would be waste.
    project_count: int = 0
    #: The topics this resume will steer the interview toward — worth showing,
    #: because it is the visible proof that the upload changed something.
    priority_topics: list[str] = []


def _resume_response(resume) -> ResumeResponse:  # noqa: ANN001 - ResumeFile, imported lazily
    """Single place the API shape is built, so the endpoints cannot diverge."""
    focus = resume.interview_focus or {}
    return ResumeResponse(
        id=resume.id,
        filename=resume.filename,
        file_size_bytes=resume.file_size_bytes,
        mime_type=resume.mime_type,
        is_primary=resume.is_primary,
        parsing_status=resume.parsing_status,
        parsed_skills=resume.parsed_skills,
        created_at=resume.created_at,
        parsing_error=resume.parsing_error,
        has_text=bool(resume.parsed_text),
        project_count=len(resume.parsed_projects or []),
        priority_topics=list(focus.get("priority_topics") or [])[:8],
    )


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
    Upload a resume, extract its text, and analyse it for interview personalisation.

    Accepted formats: PDF, DOCX. Max size: MAX_UPLOAD_SIZE_MB.

    The newest upload becomes the candidate's active (primary) resume, so
    replacing a resume is simply uploading another one.

    Three outcomes, all honest about what actually happened:

      422              the file's text could not be read (a scan, an encrypted
                       PDF, a corrupt export). Nothing is stored, and the message
                       tells the candidate how to fix it. Storing an unreadable
                       resume would leave them believing interviews use it.
      "text_only"      text extracted and stored, but AI analysis failed. The
                       interview is still personalised from the raw text.
      "completed"      text plus the structured skills/projects/focus analysis
                       that drives question selection.
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

    # ── Extract the text FIRST, before spending anything else on this file ──
    #
    # Fail fast and loudly. A resume whose text cannot be read is useless for
    # personalising an interview, so storing it and reporting success would
    # recreate the original bug in a new form: the candidate believes their resume
    # is in use while the interviewer never sees a word of it.
    try:
        resume_text = extract_text(
            file_bytes,
            file.content_type or "",
            filename=file.filename or "",
        )
    except ResumeExtractionError as exc:
        logger.warning(
            "resume_extraction_failed",
            user_id=str(current_user.user_id),
            filename=file.filename,
            reason=exc.reason,
        )
        # 422, not 415: the format is accepted, this particular file just cannot
        # be read. The message is written for the candidate and shown verbatim.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not looks_like_a_resume(resume_text):
        logger.info(
            "resume_content_suspicious",
            user_id=str(current_user.user_id),
            filename=file.filename,
            chars=len(resume_text),
        )

    # ── Analyse it (non-fatal) ──────────────────────────────────────────────
    #
    # Time-capped for the same reason report generation is: managed hosts cut the
    # request at their gateway and the resulting 502 carries no CORS headers,
    # surfacing in the browser as an opaque CORS error rather than a timeout.
    #
    # Failure here is NOT fatal. The extracted text is stored either way, and the
    # interviewer can read it directly — a personalised interview does not depend
    # on the structured analysis existing.
    analysis: ResumeAnalysisResponse | None = None
    parsing_error: str | None = None
    try:
        analysis = await asyncio.wait_for(
            analyse_resume(resume_text),
            timeout=_RESUME_ANALYSIS_BUDGET_SECONDS,
        )
    except Exception as exc:
        # Deliberately broad, and deliberately not fatal: a timeout, a provider
        # outage, or a malformed response must all leave the candidate with a
        # usable resume rather than a rejected upload.
        parsing_error = (
            "Your resume was read successfully, but the detailed skill analysis "
            "could not be completed. Interviews will still be based on your "
            "resume text."
        )
        logger.warning(
            "resume_analysis_failed_text_still_stored",
            user_id=str(current_user.user_id),
            error=type(exc).__name__,
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

    # ── The new resume becomes the active one ───────────────────────────────
    #
    # "Changing my resume" is the same action as uploading one — nobody uploads a
    # replacement and then expects interviews to keep using the old file. So the
    # newest upload is made primary and any previous primary is demoted, in the
    # same transaction as the insert so the two can never both be primary.
    await db.execute(
        update(ResumeFile)
        .where(ResumeFile.user_id == current_user.user_id, ResumeFile.is_primary.is_(True))
        .values(is_primary=False)
    )

    # Create database record
    resume = ResumeFile(
        id=file_id,
        user_id=current_user.user_id,
        filename=file.filename or "resume",
        storage_path=storage_path,
        file_size_bytes=file_size,
        mime_type=file.content_type or "application/pdf",
        is_primary=True,
        parsed_text=resume_text,
        parsing_error=parsing_error,
        # "completed" only when the structured analysis actually succeeded.
        # "text_only" is the honest middle state: readable, usable for interviews,
        # but without the skill/project breakdown.
        parsing_status="completed" if analysis else "text_only",
        parsed_skills=[s.name for s in analysis.skills] if analysis else None,
        parsed_projects=(
            [p.model_dump(mode="json") for p in analysis.projects] if analysis else None
        ),
        parsed_experience=analysis.experience.model_dump(mode="json") if analysis else None,
        interview_focus=analysis.interview_focus.model_dump(mode="json") if analysis else None,
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

    return _resume_response(resume)


@router.get("/primary", response_model=ResumeResponse | None)
async def get_primary_resume(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    The candidate's active resume, or null if they have not uploaded one.

    Declared BEFORE the "/{resume_id}" routes on purpose: FastAPI matches in
    declaration order, so a later /primary would be swallowed by the path
    parameter and fail UUID parsing.
    """
    from app.models.report import ResumeFile  # noqa: PLC0415

    resume = await db.scalar(
        select(ResumeFile)
        .where(ResumeFile.user_id == current_user.user_id, ResumeFile.is_primary.is_(True))
        .order_by(ResumeFile.created_at.desc())
        .limit(1)
    )
    return _resume_response(resume) if resume else None


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

    return [_resume_response(r) for r in resumes]


@router.patch("/{resume_id}/primary")
async def set_primary(
    resume_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import update  # noqa: PLC0415

    from app.models.report import ResumeFile  # noqa: PLC0415

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
    from supabase import create_client  # noqa: PLC0415

    from app.models.report import ResumeFile  # noqa: PLC0415

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
