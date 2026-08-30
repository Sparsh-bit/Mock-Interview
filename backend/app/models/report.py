"""
Report and Resume models — models/report.py

Tables: reports, resume_files
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Report(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    The final AI-generated performance report for a completed session.

    One report per session (enforced by unique constraint on session_id).

    The raw_report JSONB column stores the complete GLM output for:
    - Report regeneration without re-running the interview
    - Prompt quality debugging
    - Future multi-version report comparison
    """

    __tablename__ = "reports"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    overall_score_label: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="e.g. 'Excellent', 'Good', 'Needs Improvement', 'Poor'",
    )
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    readiness_level: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="interview_ready | close_to_ready | needs_more_practice | significant_gaps",
    )
    strengths: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default="{}", nullable=False,
    )
    weaknesses: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default="{}", nullable=False,
    )
    # {topic_name: score} — used to render the radar chart
    topic_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Structured list of improvement priorities with resources
    improvement_roadmap: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # URL to generated PDF in Supabase Storage
    pdf_url: Mapped[str | None] = mapped_column(Text)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Full AI-generated report JSON for auditability
    raw_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ── Relationships ──────────────────────────────────────────────────────
    session: Mapped[InterviewSession] = relationship(  # type: ignore[name-defined]
        "InterviewSession", back_populates="report",
    )
    user: Mapped[User] = relationship("User", back_populates="reports")  # type: ignore[name-defined]


class ReportJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One attempt to produce a report through the Anthropic Message Batches API.

    A batch is answered on the provider's schedule rather than inside the request, so the
    work outlives the HTTP call that started it and something has to remember it. This row
    is that memory: the batch id, which parts were submitted and what each part was for.

    UNIQUE ON session_id, AND THAT UNIQUENESS IS A SAFETY PROPERTY, not tidiness. It is what
    makes "one batch attempt per session, ever" true in the database rather than in a code
    path somebody can later add a branch to — see services/report/batch_job.may_batch. Two
    rows would mean two batches billed for one report, racing each other to write it.

    A ROW IS NEVER DELETED WHEN A JOB FAILS. The terminal row is precisely what routes this
    session to the synchronous path for good; deleting it would make the session look
    untried and start the loop the design exists to rule out.
    """

    __tablename__ = "report_jobs"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    #: Which vendor holds the batch. Stored rather than assumed: a deployment can change
    #: AI_PROVIDER between submitting a batch and collecting it, and polling the wrong
    #: vendor for someone else's batch id is a confusing way to fail.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The provider's own batch id, used to poll and to fetch results.
    batch_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    #: processing | completed | failed | abandoned — see batch_job.JobStatus.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    #: custom_id -> what that part was asked to do, so a result can be matched back to the
    #: questions it graded. The Batches API returns results in COMPLETION order, so without
    #: this a six-question analysis could be attached to the wrong six questions.
    parts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Consecutive failures to retrieve the batch's status. Reset on any successful poll;
    #: past a small ceiling the job is abandoned, because a batch nobody can see is a report
    #: that would otherwise wait forever.
    lookup_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Why it ended, when it ended badly. Null on a healthy job.
    error: Mapped[str | None] = mapped_column(Text)
    #: Which generation strategy submitted this, mirroring reports.raw_report.strategy.
    strategy: Mapped[str | None] = mapped_column(String(32))

    # ── Relationships ──────────────────────────────────────────────────────
    #
    # Deliberately none. Nothing needs to walk from a session or a user TO its batch job —
    # every read starts from the session id — and adding a back-reference would put this
    # table into the load path of models that are queried on every authenticated request.


class ResumeFile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    An uploaded candidate resume file.

    The binary is stored in Supabase Storage; this record stores the metadata
    and the AI-parsed content used for interview personalization.
    """

    __tablename__ = "resume_files"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Supabase Storage bucket path: e.g. "resumes/{user_id}/{uuid}.pdf"
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # AI-extracted structured data
    parsed_skills: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    parsed_projects: Mapped[list | None] = mapped_column(JSONB)
    parsed_experience: Mapped[dict | None] = mapped_column(JSONB)
    interview_focus: Mapped[dict | None] = mapped_column(
        JSONB, comment="Resume analyzer output: strong_areas, weak_areas, priority_topics",
    )
    # Only one resume can be primary at a time (enforced by application logic)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # The extracted plain text. Stored because it is what the interviewer
    # ultimately reads: the structured columns above are a condensed view, and if
    # AI analysis fails the raw text still personalises the interview on its own.
    # Keeping it also means re-analysis never needs the original file back out of
    # storage.
    parsed_text: Mapped[str | None] = mapped_column(Text)
    # Why parsing failed, in words the candidate can act on ("that PDF is a scan,
    # upload the original export"). Null when parsing succeeded.
    parsing_error: Mapped[str | None] = mapped_column(Text)
    # "pending" | "parsing" | "completed" | "failed"
    parsing_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False,
    )
    # What `services/resume/integrity.assess` found in the uploaded bytes: text hidden from
    # a human reader, phrasing aimed at the grader, or both. NULL on a clean resume — which
    # is nearly all of them — so "show me the flagged ones" is `IS NOT NULL` over a small
    # partial index rather than a filter across every upload ever made.
    #
    # NEVER READ BY THE INTERVIEW PATH. This is a note for a person, not a control: the
    # thing that actually protects a score from a resume is the trust boundary in
    # services/ai/untrusted.py, and it holds whether or not this column has anything in it.
    integrity_flags: Mapped[dict | None] = mapped_column(JSONB)

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped[User] = relationship("User", back_populates="resume_files")  # type: ignore[name-defined]
