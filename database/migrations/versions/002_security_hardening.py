"""
Security & Performance Hardening — 002_security_hardening.py
Revision: 002

Enables Row Level Security on every public application table (Supabase
auto-exposes any public table without RLS via its PostgREST API using the
publicly-embedded anon key -- this app's backend connects directly via
asyncpg and never relies on that API, so RLS is enabled with no permissive
policies, which fully denies anon/authenticated access while leaving the
backend's direct connection unaffected).

Also adds indexes for three foreign keys that lacked one (flagged by
Supabase's performance advisor): interview_sessions.resume_file_id,
answers.voice_transcript_id, system_prompts.created_by.
"""

from __future__ import annotations

from alembic import op

# revision identifiers
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | None = None
depends_on: str | None = None

_TABLES = [
    "answers",
    "audit_logs",
    "companies",
    "follow_up_questions",
    "interview_sessions",
    "interview_tracks",
    "profiles",
    "question_categories",
    "questions",
    "reports",
    "resume_files",
    "scores",
    "subtopics",
    "system_prompts",
    "topics",
    "users",
    "voice_transcripts",
]


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    op.create_index(
        "ix_interview_sessions_resume_file_id", "interview_sessions", ["resume_file_id"]
    )
    op.create_index("ix_answers_voice_transcript_id", "answers", ["voice_transcript_id"])
    op.create_index("ix_system_prompts_created_by", "system_prompts", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_system_prompts_created_by", table_name="system_prompts")
    op.drop_index("ix_answers_voice_transcript_id", table_name="answers")
    op.drop_index("ix_interview_sessions_resume_file_id", table_name="interview_sessions")

    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
