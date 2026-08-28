"""
Session models — models/session.py

Tables: interview_sessions, answers, scores, voice_transcripts

These are the high-write, operationally critical tables.
The Interview Orchestrator reads and writes interview_sessions on every turn.
Answers and scores are written after each question-answer cycle.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SessionStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"



class InterviewSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A single interview attempt by a user.

    The Interview Orchestrator manages session state via the metadata JSONB column,
    which stores: topic progress, difficulty adjustments, questions asked per topic,
    and orchestrator-internal state.

    Status transitions (enforced by the orchestrator):
      pending → active → completed
      pending → active → abandoned
    """

    __tablename__ = "interview_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_tracks.id"), nullable=False, index=True,
    )
    resume_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resume_files.id", ondelete="SET NULL"), nullable=True,
    )
    # "pending" | "active" | "completed" | "abandoned"
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True,
    )
    # "text" | "voice"
    mode: Mapped[str] = mapped_column(String(10), default="text", nullable=False)
    current_topic_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    # Orchestrator state — topic coverage map, difficulty state, question history
    session_metadata: Mapped[dict | None] = mapped_column(JSONB)

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped[User] = relationship("User", back_populates="sessions")  # type: ignore[name-defined]
    track: Mapped[InterviewTrack] = relationship("InterviewTrack", back_populates="sessions")  # type: ignore[name-defined]
    answers: Mapped[list[Answer]] = relationship(
        "Answer", back_populates="session", cascade="all, delete-orphan",
    )
    scores: Mapped[list[Score]] = relationship(
        "Score", back_populates="session",
    )
    voice_transcripts: Mapped[list[VoiceTranscript]] = relationship(
        "VoiceTranscript", back_populates="session", cascade="all, delete-orphan",
    )
    report: Mapped[Report | None] = relationship(  # type: ignore[name-defined]
        "Report", back_populates="session", uselist=False,
    )


class Answer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    The candidate's raw answer to a question in a session.
    One Answer per Question per Session.
    """

    __tablename__ = "answers"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id"), nullable=False, index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    voice_transcript_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voice_transcripts.id", ondelete="SET NULL", name="fk_answer_voice_transcript_id"), nullable=True,
    )
    response_time_seconds: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int | None] = mapped_column(Integer)
    #: Delivery for THIS answer, including where each pause fell:
    #: {filler_count, pause_count, total_pause_seconds, words, speaking_seconds,
    #:  pauses: [{wordIndex, seconds}]}
    #:
    #: The session keeps running totals for the report's headline metrics; this
    #: keeps the detail, which is what makes it possible to replay a candidate's
    #: own answer back to them with the hesitations marked. A total cannot do that.
    delivery: Mapped[dict | None] = mapped_column(JSONB)
    #: Cached coaching for this answer: the model answer the candidate should have
    #: given, what was missing, the key points, and a verdict line. Written against
    #: what they actually said, generated on demand, and stored whole so a reload
    #: never costs a second billed call or silently drops half the content.
    model_answer: Mapped[dict | None] = mapped_column(JSONB)
    model_answer_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Relationships ──────────────────────────────────────────────────────
    session: Mapped[InterviewSession] = relationship("InterviewSession", back_populates="answers")
    question: Mapped[Question] = relationship("Question", back_populates="answers")  # type: ignore[name-defined]
    score: Mapped[Score | None] = relationship(
        "Score", back_populates="answer", uselist=False,
    )
    voice_transcript: Mapped[VoiceTranscript | None] = relationship(
        "VoiceTranscript",
        foreign_keys=[voice_transcript_id],
        primaryjoin="Answer.voice_transcript_id == VoiceTranscript.id",
    )


class Score(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    AI-generated evaluation for a single Answer.

    One Score per Answer (enforced by unique constraint on answer_id).
    All numeric scores are on a 0.0–10.0 scale.

    raw_evaluation stores the complete AI response for:
    - Debugging evaluation quality
    - Future re-evaluation without re-running the interview
    - Prompt improvement analytics
    """

    __tablename__ = "scores"

    answer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    technical_score: Mapped[float] = mapped_column(Float, nullable=False)
    communication_score: Mapped[float] = mapped_column(Float, nullable=False)
    completeness_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Weighted composite: 0.4*technical + 0.2*communication + 0.25*completeness + 0.15*confidence
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    strengths: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default="{}", nullable=False,
    )
    weaknesses: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default="{}", nullable=False,
    )
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    is_bluffing_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_evaluation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ── Relationships ──────────────────────────────────────────────────────
    answer: Mapped[Answer] = relationship("Answer", back_populates="score")
    session: Mapped[InterviewSession] = relationship("InterviewSession", back_populates="scores")


class VoiceTranscript(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Whisper speech-to-text result for a voice-mode answer."""

    __tablename__ = "voice_transcripts"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    answer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL", name="fk_voice_transcript_answer_id", use_alter=True), nullable=True,
    )
    raw_transcript: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    model_used: Mapped[str] = mapped_column(String(50), default="whisper-1", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    session: Mapped[InterviewSession] = relationship(
        "InterviewSession", back_populates="voice_transcripts",
    )


class InterviewFeedback(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    What the candidate thought of the interview, as stars out of five.

    NOT `RatingEvent`, WHICH IS A DIFFERENT THING ENTIRELY. That table is the ELO-style
    ledger of how well somebody PERFORMED; this is how well the PRODUCT performed. Two
    "ratings" in one system is exactly the naming collision that produces a query joining the
    wrong one, so they are named for what they measure rather than for the word they share.

    A SEPARATE TABLE RATHER THAN COLUMNS ON `interview_sessions`, for the deployment reason
    that migration 021 sets out at length: migrations here are applied BY HAND against
    Supabase, so there is always a window where the code is live and the schema is not.
    Columns on `interview_sessions` would put the new field in every SELECT against the single
    busiest table in the product — the interview itself would 500 until somebody remembered to
    run this. A new table cannot do that: nothing existing reads it, so before the migration
    the feature simply has nothing to show and every other path is untouched.

    ONE RATING PER SESSION, enforced by a UNIQUE constraint rather than by the endpoint
    checking first. A read-then-write check has a window between the read and the write, and
    two taps on a slow connection land in it.

    CASCADE ON DELETE. Feedback about a deleted interview is feedback about nothing, and
    account deletion has to be able to remove it — see the note in admin.delete_user about
    ORM deletes leaving orphans when the cascade is not on the database.
    """

    __tablename__ = "interview_feedback"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    #: Denormalised from the session so the admin aggregate does not have to join to answer
    #: "how many distinct people rated us", and so a tenancy check has a column to compare.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    #: 1-5. Constrained in the DATABASE as well as in the request model, because the request
    #: model is one refactor away from being bypassed by a background job or a fixture.
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Optional and length-capped. Free text from a candidate is the one field here that could
    #: carry personal data they did not mean to publish, so it is never shown outside admin.
    comment: Mapped[str | None] = mapped_column(String(1000))

    __table_args__ = (
        CheckConstraint("stars >= 1 AND stars <= 5", name="ck_interview_feedback_stars"),
    )
