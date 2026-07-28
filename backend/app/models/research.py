"""
Company Interview Research — models/research.py

A cache of what a company's interview actually looks like: the real rounds,
previously-asked questions, and the topics they lean on.

Why this is a table rather than a live web search at interview time:
  - Cost. A live search per interview is billed every single time, for
    information that changes a few times a year at most.
  - Latency. The candidate would wait on search + read before the first
    question. Reading a row is effectively free.
  - Quality. Curated, reviewable rows beat whatever a search returns on the
    day, and a bad result can be corrected in place.

Rows are seeded from `knowledge/research/*.yaml` (see scripts/seed_research.py)
and refreshed by re-running the seeder, so refreshing the research is a
deliberate act rather than a per-interview expense.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CompanyResearch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Interview intelligence for one (company, program) pair.

    `program` is "" for company-wide research that applies to every program, so
    a lookup can fall back to it when a specific program has no row.
    """

    __tablename__ = "company_research"
    __table_args__ = (
        UniqueConstraint("company_slug", "program_slug", name="uq_company_research_company_program"),
        Index("ix_company_research_lookup", "company_slug", "program_slug"),
    )

    #: Normalised company key, e.g. "cognizant", "tcs".
    company_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Normalised program key, e.g. "genc", "genc-next", "ninja". "" = any.
    program_slug: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    #: Human-readable labels for prompts and UI.
    company_name: Mapped[str] = mapped_column(String(128), nullable=False)
    program_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    #: Ordered rounds: [{name, duration_minutes, description}]
    rounds: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    #: Previously-asked questions:
    #: [{question, topic, round, difficulty, kind}]
    previous_questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    #: Topics this company leans on, most-emphasised first.
    focus_topics: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    #: Short, candidate-facing preparation notes.
    tips: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    #: Where this came from, so a stale row can be re-verified.
    sources: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
