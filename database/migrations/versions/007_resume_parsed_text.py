"""store extracted resume text and the reason parsing failed

Resume upload has always stored the file and left `parsing_status` at "pending"
forever — nothing ever extracted the text, so an uploaded resume could not affect
an interview. Wiring the extraction up needs somewhere to put the result:

  parsed_text    the extracted plain text. This is what the interviewer actually
                 reads. The existing parsed_skills / parsed_projects /
                 parsed_experience / interview_focus columns hold the condensed
                 AI view; the raw text is kept alongside them so that (a) an
                 interview is still personalised when AI analysis fails, and
                 (b) re-analysis never has to fetch the file back out of storage.

  parsing_error  why it failed, phrased for the candidate ("that PDF is a scan —
                 upload the original export"). Null on success. Without this a
                 failure is indistinguishable from "not processed yet", which is
                 the ambiguity that let the pending state go unnoticed.

Both nullable with no default: every existing row predates extraction, and NULL is
the honest value for "never parsed" rather than an empty string that reads as
"parsed, found nothing".

Revision ID: 007
Revises: 006
"""

from __future__ import annotations

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels = None
depends_on = None

_COLUMNS = ("parsed_text", "parsing_error")


def upgrade() -> None:
    bind = op.get_bind()

    if not bind.exec_driver_sql(
        "SELECT to_regclass('public.resume_files') IS NOT NULL"
    ).scalar():
        # The table is created by an earlier migration; if it is absent, that is a
        # separate problem and inventing it here would duplicate that migration.
        return

    for column in _COLUMNS:
        # IF NOT EXISTS so this is safe on a database that already has them and
        # re-runnable if it half-applied.
        op.execute(f"ALTER TABLE resume_files ADD COLUMN IF NOT EXISTS {column} TEXT")


def downgrade() -> None:
    for column in _COLUMNS:
        op.execute(f"ALTER TABLE resume_files DROP COLUMN IF EXISTS {column}")
