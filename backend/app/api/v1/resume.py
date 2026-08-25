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
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select, update

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys
from app.db.session import AsyncSession, get_db
from app.events import (
    ResumeUploadedEvent,
    ResumeUploadedPayload,
    get_event_emitter,
)
from app.events.emitter import EventEmitter
from app.services.resume import (
    ResumeExtractionError,
    extract_text,
    looks_like_a_resume,
)
from app.services.resume.analyser import ResumeAnalysisOutcome, analyse_resume

logger = structlog.get_logger(__name__)
router = APIRouter()

#: The wall-clock ceiling on resume analysis lives in
#: settings.RESUME_ANALYSIS_BUDGET_SECONDS and is applied inside `analyse_resume`,
#: which is the function that fans the work out and therefore the only place that
#: can keep the half that finished when the other one does not. It used to be a
#: hardcoded 45.0 here wrapped around a single `asyncio.wait_for`, which had no way
#: to salvage anything — read the header of services/resume/analyser.py.

#: Rate limit on upload. Each one reads a file AND runs a billed AI analysis, so
#: an unthrottled upload endpoint is both a spend and a CPU amplifier: a loop of
#: 10 MB PDFs would pin the worker parsing them. Shares the AI bucket.
_resume_upload_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_ai(user_id),
    action="uploading a resume",
)

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}


@lru_cache(maxsize=1)
def _storage_client() -> Any:
    """
    The process-wide Supabase client, built once.

    `create_client` was being called per request, on both the upload and the delete
    path. Each call builds a fresh set of HTTP clients, so every resume upload paid
    a new TLS handshake to Supabase before it could send a byte — the same
    connection-pool-per-request leak the AI provider factory has a long comment
    about avoiding. The underlying client is httpx-based and thread-safe, which
    matters because the calls below run in a worker thread.
    """
    from supabase import create_client  # noqa: PLC0415

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


class ResumeResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_size_bytes: int
    mime_type: str
    is_primary: bool
    #: "completed" | "partial" | "text_only" | "failed" | "pending"
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
    dependencies=[Depends(_resume_upload_rate_limit)],
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

    Four outcomes, all honest about what actually happened:

      422              the file's text could not be read (a scan, an encrypted
                       PDF, a corrupt export). Nothing is stored, and the message
                       tells the candidate how to fix it. Storing an unreadable
                       resume would leave them believing interviews use it.
      "text_only"      text extracted and stored, but AI analysis failed. The
                       interview is still personalised from the raw text.
      "partial"        one half of the analysis landed and the other did not —
                       skills without projects, or the reverse. A REAL state, not a
                       tidy-up: the analysis is requested as two concurrent halves
                       and either can fail on its own. Reporting it as "completed"
                       is exactly the bug that was reported ("skills and projects
                       are not been able to fetch") — the upload said "Read and
                       analysed" over an empty analysis.
      "completed"      text plus the full structured skills/projects/focus analysis
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
    #
    # IN A WORKER THREAD, because pypdf and python-docx are pure CPU and pure
    # blocking. A 10 MB PDF with a pathological text layer holds the event loop for
    # seconds, and while it does, every other request this worker is serving —
    # interview turns, quiz starts, report polls — is frozen behind it. One upload
    # is not allowed to be everyone else's latency.
    try:
        resume_text = await asyncio.to_thread(
            extract_text,
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

    # ── Store the file and analyse it, AT THE SAME TIME ─────────────────────
    #
    # These two have nothing to say to each other: the storage write needs the
    # bytes, the analysis needs the text, and neither reads the other's result. They
    # were nonetheless strictly sequential, with the file upload waiting behind an
    # AI call that measured 118-214 seconds — so the candidate paid for both ends of
    # a request that only ever needed the longer one. Overlapping them is most of
    # the answer to "make sure that the resume uploading also works faster".
    #
    # The storage write goes through `asyncio.to_thread` because supabase-py's
    # client is SYNCHRONOUS. Called directly from this coroutine it blocked the
    # whole event loop for the duration of a multi-megabyte HTTP PUT — not just this
    # request, every request this worker had in flight.
    file_id = uuid.uuid4()
    storage_path = f"resumes/{current_user.user_id}/{file_id}/{file.filename}"

    def _store_file() -> None:
        _storage_client().storage.from_(settings.SUPABASE_STORAGE_BUCKET_RESUMES).upload(
            storage_path,
            file_bytes,
            {"content-type": file.content_type or "application/pdf"},
        )

    storage_task = asyncio.create_task(asyncio.to_thread(_store_file))

    # Analysis failure is NOT fatal and never raises: `analyse_resume` bounds itself
    # with settings.RESUME_ANALYSIS_BUDGET_SECONDS and isolates its two halves, so
    # the worst case here is an outcome with nothing in it. The extracted text is
    # stored regardless and the interviewer can read it directly — a personalised
    # interview does not depend on the structured analysis existing.
    outcome: ResumeAnalysisOutcome = await analyse_resume(resume_text)
    analysis = outcome.analysis
    parsing_error = outcome.candidate_message()

    # Awaited AFTER the analysis, so its duration is hidden inside it in the normal
    # case. A storage failure is still fatal to the upload: a row pointing at a file
    # that was never written is worse than a failed upload the candidate can retry.
    await storage_task

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
        # Three states — completed / partial / text_only. The decision lives on the
        # outcome rather than here, because it is the claim this endpoint makes to
        # the candidate about their own upload and it was the false one: see
        # ResumeAnalysisOutcome.parsing_status.
        parsing_status=outcome.parsing_status,
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
        parsing_status=resume.parsing_status,
        skills=len(resume.parsed_skills or []),
        projects=len(resume.parsed_projects or []),
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

    # Delete from Supabase Storage — in a thread, because supabase-py is synchronous
    # and a blocking network call in a coroutine stalls every other request on this
    # worker, not just this one.
    storage_path = resume.storage_path
    try:
        await asyncio.to_thread(
            lambda: _storage_client()
            .storage.from_(settings.SUPABASE_STORAGE_BUCKET_RESUMES)
            .remove([storage_path])
        )
    except Exception:
        logger.exception("supabase_storage_delete_failed", path=storage_path)

    await db.delete(resume)

    logger.info("resume_deleted", resume_id=str(resume_id))
