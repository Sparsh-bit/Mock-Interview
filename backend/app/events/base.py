"""
Platform Events — events/base.py

Defines all structured event types emitted by the interview platform.

Naming convention: <domain>.<past_tense_verb>
  - "interview.started" not "interview.start"
  - "answer.evaluated" not "answer.evaluate"

Rules:
  - Events are IMMUTABLE once created (frozen=True).
  - Events are APPEND-ONLY — never rename or remove EventType members.
    Old values may be deprecated but must never be deleted (replay safety).
  - Every event MUST have a payload typed as a dedicated Pydantic model.
    No untyped dict payloads.
  - user_id and session_id are top-level for efficient DB indexing.
  - version field enables schema evolution without breaking event consumers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


# ─── Event type registry ──────────────────────────────────────────────────────


class EventType(StrEnum):
    """
    Canonical event type identifiers for the interview platform.

    APPEND-ONLY: Never rename or remove values once deployed to production.
    Add deprecation comments instead.
    """

    # ── Interview lifecycle ───────────────────────────────────────────────
    INTERVIEW_STARTED = "interview.started"
    INTERVIEW_COMPLETED = "interview.completed"
    INTERVIEW_ABANDONED = "interview.abandoned"

    # ── In-session events ─────────────────────────────────────────────────
    QUESTION_ASKED = "interview.question_asked"
    ANSWER_SUBMITTED = "interview.answer_submitted"
    ANSWER_EVALUATED = "interview.answer_evaluated"
    FOLLOW_UP_TRIGGERED = "interview.follow_up_triggered"

    # ── Reports ───────────────────────────────────────────────────────────
    REPORT_GENERATED = "report.generated"
    REPORT_EXPORTED = "report.exported"

    # ── Resume ────────────────────────────────────────────────────────────
    RESUME_UPLOADED = "resume.uploaded"
    RESUME_PARSED = "resume.parsed"
    RESUME_PARSE_FAILED = "resume.parse_failed"

    # ── User ──────────────────────────────────────────────────────────────
    USER_REGISTERED = "user.registered"
    USER_PROFILE_UPDATED = "user.profile_updated"

    # ── System ────────────────────────────────────────────────────────────
    AI_PROVIDER_ERROR = "system.ai_provider_error"
    RATE_LIMIT_HIT = "system.rate_limit_hit"


# ─── Base event ───────────────────────────────────────────────────────────────


class BaseEvent(BaseModel):
    """
    Base class for all platform events.

    Every concrete event class extends BaseEvent and provides a typed payload.
    Do not use this class directly — always use a concrete subclass.
    """

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: EventType
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    # Subject identifiers — stored as top-level columns in audit_logs for indexing
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    # Schema version — increment when payload shape changes
    version: int = 1

    model_config = {"frozen": True}


# ─── Interview lifecycle events ───────────────────────────────────────────────


class InterviewStartedPayload(BaseModel):
    track_id: uuid.UUID
    track_name: str
    mode: str  # "text" | "voice"
    resume_file_id: uuid.UUID | None = None


class InterviewStartedEvent(BaseEvent):
    event_type: EventType = EventType.INTERVIEW_STARTED
    payload: InterviewStartedPayload


class InterviewCompletedPayload(BaseModel):
    duration_seconds: int
    questions_asked: int
    overall_score: float | None = None


class InterviewCompletedEvent(BaseEvent):
    event_type: EventType = EventType.INTERVIEW_COMPLETED
    payload: InterviewCompletedPayload


class InterviewAbandonedPayload(BaseModel):
    questions_asked: int
    reason: str  # "user_exit" | "timeout" | "error"


class InterviewAbandonedEvent(BaseEvent):
    event_type: EventType = EventType.INTERVIEW_ABANDONED
    payload: InterviewAbandonedPayload


# ─── In-session events ────────────────────────────────────────────────────────


class QuestionAskedPayload(BaseModel):
    question_id: uuid.UUID
    topic_name: str
    difficulty: str  # "easy" | "medium" | "hard"
    question_number: int  # 1-indexed position in the session
    is_follow_up: bool = False


class QuestionAskedEvent(BaseEvent):
    event_type: EventType = EventType.QUESTION_ASKED
    payload: QuestionAskedPayload


class AnswerSubmittedPayload(BaseModel):
    question_id: uuid.UUID
    answer_id: uuid.UUID
    response_time_seconds: int
    word_count: int
    mode: str  # "text" | "voice"


class AnswerSubmittedEvent(BaseEvent):
    event_type: EventType = EventType.ANSWER_SUBMITTED
    payload: AnswerSubmittedPayload


class AnswerEvaluatedPayload(BaseModel):
    answer_id: uuid.UUID
    question_id: uuid.UUID
    overall_score: float   # 0.0–10.0
    technical_score: float
    communication_score: float
    is_bluffing_detected: bool
    evaluation_time_ms: int  # Time taken for AI evaluation


class AnswerEvaluatedEvent(BaseEvent):
    event_type: EventType = EventType.ANSWER_EVALUATED
    payload: AnswerEvaluatedPayload


class FollowUpTriggeredPayload(BaseModel):
    parent_question_id: uuid.UUID
    follow_up_question_id: uuid.UUID
    trigger_condition: str


class FollowUpTriggeredEvent(BaseEvent):
    event_type: EventType = EventType.FOLLOW_UP_TRIGGERED
    payload: FollowUpTriggeredPayload


# ─── Report events ────────────────────────────────────────────────────────────


class ReportGeneratedPayload(BaseModel):
    report_id: uuid.UUID
    overall_score: float
    generation_time_ms: int
    questions_evaluated: int


class ReportGeneratedEvent(BaseEvent):
    event_type: EventType = EventType.REPORT_GENERATED
    payload: ReportGeneratedPayload


class ReportExportedPayload(BaseModel):
    report_id: uuid.UUID
    format: str  # "pdf" | "json"
    file_size_bytes: int | None = None


class ReportExportedEvent(BaseEvent):
    event_type: EventType = EventType.REPORT_EXPORTED
    payload: ReportExportedPayload


# ─── Resume events ────────────────────────────────────────────────────────────


class ResumeUploadedPayload(BaseModel):
    resume_file_id: uuid.UUID
    filename: str
    file_size_bytes: int
    mime_type: str


class ResumeUploadedEvent(BaseEvent):
    event_type: EventType = EventType.RESUME_UPLOADED
    payload: ResumeUploadedPayload


class ResumeParsedPayload(BaseModel):
    resume_file_id: uuid.UUID
    skills_count: int
    projects_count: int
    parsing_time_ms: int


class ResumeParsedEvent(BaseEvent):
    event_type: EventType = EventType.RESUME_PARSED
    payload: ResumeParsedPayload


class ResumeParseFailedPayload(BaseModel):
    resume_file_id: uuid.UUID
    error_message: str


class ResumeParseFailedEvent(BaseEvent):
    event_type: EventType = EventType.RESUME_PARSE_FAILED
    payload: ResumeParseFailedPayload


# ─── System events ────────────────────────────────────────────────────────────


class AIProviderErrorPayload(BaseModel):
    provider: str
    model: str
    error_message: str
    status_code: int | None = None
    is_rate_limit: bool = False


class AIProviderErrorEvent(BaseEvent):
    event_type: EventType = EventType.AI_PROVIDER_ERROR
    payload: AIProviderErrorPayload
