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

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SessionStatus(str, enum.Enum):
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
