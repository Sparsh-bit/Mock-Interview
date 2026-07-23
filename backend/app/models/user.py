"""
User models — models/user.py

Tables: users, profiles

users — the core identity record linked to Supabase Auth.
profiles — extended profile data in a 1:1 relationship with users.

Architecture note:
  Supabase Auth manages authentication in the auth.users table (internal).
  Our users table stores the application-level user record keyed by supabase_uid.
  On first login, the backend syncs the Supabase auth user to our users table.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Core application user record.
    Created/synced on first Supabase auth login via POST /api/v1/auth/profile.
    """

    __tablename__ = "users"

    supabase_uid: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True,
        comment="Supabase auth.users.id — used for JWT verification",
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    profile: Mapped[Profile] = relationship(
        "Profile", back_populates="user", uselist=False, cascade="all, delete-orphan",
    )
    sessions: Mapped[list[InterviewSession]] = relationship(  # type: ignore[name-defined]
        "InterviewSession", back_populates="user",
    )
    reports: Mapped[list[Report]] = relationship(  # type: ignore[name-defined]
        "Report", back_populates="user",
    )
    resume_files: Mapped[list[ResumeFile]] = relationship(  # type: ignore[name-defined]
        "ResumeFile", back_populates="user",
    )


class Profile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Extended profile data. One-to-one with User.
    Populated by the candidate on their profile settings page.
    """

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )
    full_name: Mapped[str | None] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    target_company: Mapped[str | None] = mapped_column(String(100))
    experience_years: Mapped[int | None] = mapped_column(Integer)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    github_url: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped[User] = relationship("User", back_populates="profile")
