"""
Company models — models/company.py

Tables: companies, interview_tracks, question_categories

Hierarchy: Company → InterviewTrack → QuestionCategory → (topics, in question.py)

Example:
  Company: Cognizant
  Track: Digital Nurture Java FSE
  Category: Java Core | Spring Boot | Databases | Microservices
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Company(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A company that offers one or more interview tracks on the platform."""

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
        comment="URL-safe identifier, e.g. 'cognizant'",
    )
    logo_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    tracks: Mapped[list[InterviewTrack]] = relationship(
        "InterviewTrack", back_populates="company", cascade="all, delete-orphan",
    )


class InterviewTrack(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A specific interview track within a company.
    E.g., Cognizant → Digital Nurture Java FSE
    """

    __tablename__ = "interview_tracks"
    __table_args__ = (
        UniqueConstraint("company_id", "slug", name="uq_tracks_company_slug"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # "beginner" | "intermediate" | "advanced"
    difficulty_level: Mapped[str] = mapped_column(
        String(20), default="intermediate", nullable=False,
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    company: Mapped[Company] = relationship("Company", back_populates="tracks")
    categories: Mapped[list[QuestionCategory]] = relationship(
        "QuestionCategory", back_populates="track", cascade="all, delete-orphan",
        order_by="QuestionCategory.order_index",
    )
    sessions: Mapped[list[InterviewSession]] = relationship(  # type: ignore[name-defined]
        "InterviewSession", back_populates="track",
    )


class QuestionCategory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A high-level topic category within a track.
    E.g., "Java Core", "Spring Boot", "Databases", "System Design"
    """

    __tablename__ = "question_categories"
    __table_args__ = (
        UniqueConstraint("track_id", "slug", name="uq_categories_track_slug"),
    )

    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_tracks.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Relative weight for final score calculation (sum of all weights = 1.0 per track)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    track: Mapped[InterviewTrack] = relationship("InterviewTrack", back_populates="categories")
    topics: Mapped[list[Topic]] = relationship(  # type: ignore[name-defined]
        "Topic", back_populates="category", cascade="all, delete-orphan",
        order_by="Topic.order_index",
    )
