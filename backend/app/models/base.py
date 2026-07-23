"""
SQLAlchemy declarative base and shared mixins — models/base.py

All model classes must inherit from Base (for SQLAlchemy registration) and
optionally TimestampMixin (for created_at/updated_at) and UUIDPrimaryKeyMixin.

Design decisions:
  - UUIDs as primary keys: compatible with Supabase, client-generatable, no hot-spot.
  - server_default=func.gen_random_uuid(): UUID generated at the DB level when
    the application does not provide one. This enables bulk inserts without
    pre-generating UUIDs in Python.
  - timezone=True on all DateTime columns: all timestamps are UTC-aware.
  - updated_at uses onupdate: SQLAlchemy calls func.now() on every UPDATE
    statement automatically.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base for all ORM models."""


class TimestampMixin:
    """
    Adds created_at and updated_at timestamp columns.

    Both are stored as timezone-aware UTC datetimes.
    Include this on every mutable table.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=False,  # Only index created_at if you query by date range; add per-table
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """
    UUID primary key with server-side generation.

    gen_random_uuid() is a PostgreSQL built-in (pgcrypto or pg 13+).
    The application layer may also set id explicitly before insert.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
