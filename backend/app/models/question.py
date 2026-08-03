"""
Question models — models/question.py

Tables: topics, subtopics, questions, follow_up_questions

Hierarchy: QuestionCategory → Topic → Subtopic → Question → FollowUpQuestion

The Interview Orchestrator navigates this hierarchy when selecting questions.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class QuestionDifficulty(enum.StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

class QuestionType(enum.StrEnum):
    CONCEPTUAL = "conceptual"
    PRACTICAL = "practical"
    SCENARIO = "scenario"
    CODING = "coding"
    DESIGN = "design"



class Topic(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A specific topic within a QuestionCategory.
    E.g., "OOP Concepts", "Java Collections Framework", "Multithreading"
    """

    __tablename__ = "topics"

    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_categories.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    category: Mapped[QuestionCategory] = relationship(  # type: ignore[name-defined]
        "QuestionCategory", back_populates="topics",
    )
    subtopics: Mapped[list[Subtopic]] = relationship(
        "Subtopic", back_populates="topic", cascade="all, delete-orphan",
        order_by="Subtopic.order_index",
    )
    questions: Mapped[list[Question]] = relationship(
        "Question", back_populates="topic",
    )


class Subtopic(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Fine-grained subtopic within a Topic.
    E.g., Topic: "Java Collections" → Subtopic: "HashMap Internals"
    """

    __tablename__ = "subtopics"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    topic: Mapped[Topic] = relationship("Topic", back_populates="subtopics")
    questions: Mapped[list[Question]] = relationship(
        "Question", back_populates="subtopic",
    )


class Question(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A single interview question.

    Populated from app/data/java_fundamentals.py — by scripts/seed_db.py, and at runtime by
    orchestrator._ensure_seed_questions when a track has no bank questions yet.
    The Interview Orchestrator selects questions based on topic, difficulty, and
    the candidate's resume analysis results.
    """

    __tablename__ = "questions"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    subtopic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subtopics.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    #: Which session generated this question, or NULL for the shared bank.
    #:
    #:   NULL      a question bank row — seeded, generic, reusable by anyone.
    #:   non-NULL  generated for exactly this session. Never served to another.
    #:
    #: This is a tenancy boundary, not a bookkeeping field. Three of the four
    #: places that create questions produce text specific to one person: a
    #: cross-question quotes the candidate's own words, a planned question can
    #: be tailored to their resume, and an adaptive question targets the gaps
    #: they just revealed. Before this column existed all of them were written
    #: into the shared pool under a topic, and the pool queries selected the
    #: whole track — so one candidate's spoken answer could be, and was, served
    #: verbatim to a different candidate as a fresh question.
    #:
    #: EVERY POOL QUERY MUST FILTER `session_id IS NULL`. A session reaches its
    #: own generated questions by explicit id from session_metadata, never by
    #: search, so the filter costs those paths nothing.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # "easy" | "medium" | "hard"
    difficulty: Mapped[str] = mapped_column(String(20), default="medium", nullable=False, index=True)
    # "conceptual" | "practical" | "scenario" | "coding" | "design"
    question_type: Mapped[str] = mapped_column(String(30), default="conceptual", nullable=False)
    # Keywords the AI evaluator uses to assess answer completeness
    expected_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default="{}", nullable=False,
    )
    ideal_answer: Mapped[str | None] = mapped_column(Text)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Analytics — updated by background job
    times_asked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────────
    topic: Mapped[Topic] = relationship("Topic", back_populates="questions")
    subtopic: Mapped[Subtopic | None] = relationship("Subtopic", back_populates="questions")
    follow_ups: Mapped[list[FollowUpQuestion]] = relationship(
        "FollowUpQuestion", back_populates="parent_question", cascade="all, delete-orphan",
        order_by="FollowUpQuestion.order_index",
    )
    answers: Mapped[list[Answer]] = relationship(  # type: ignore[name-defined]
        "Answer", back_populates="question",
    )


class FollowUpQuestion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A follow-up question linked to a parent question.

    CURRENTLY UNUSED, and the docstring used to claim otherwise: it said "the
    Interview Orchestrator selects follow-ups based on the AI evaluator's
    assessment", which was never true in this codebase. Nothing reads this table.

    Follow-ups are generated live instead — orchestrator._generate_cross_question
    builds one from what the candidate actually just said, which is strictly
    better than picking a pre-written one, because it can quote them. The table
    was written by the old YAML seeder and queried by nothing.

    Kept because the schema is harmless and a pre-written fallback for when the AI
    is unavailable is a plausible future use. If that never happens, drop it —
    but do not wire it up on the strength of the old docstring.
    """

    __tablename__ = "follow_up_questions"

    parent_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # "incomplete_answer" | "bluffing_detected" | "strong_answer_deepen" | "always"
    trigger_condition: Mapped[str] = mapped_column(
        String(50), default="always", nullable=False,
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    parent_question: Mapped[Question] = relationship(
        "Question", back_populates="follow_ups",
    )
