"""resume_files.integrity_flags — what a resume was caught doing

WHY A COLUMN AND NOT A LOG LINE. The finding is about one specific uploaded file and it
needs to still be findable when somebody asks "which resumes have we flagged?" a fortnight
later. A structured log answers that only for as long as the log is retained and only if
somebody can query it; the row is the thing the admin surface joins against.

NULLABLE, WITH NO DEFAULT AND NO BACKFILL, deliberately. Nearly every resume is clean, and
`WHERE integrity_flags IS NOT NULL` over the partial index below is a small, cheap question.
A `server_default` of `'{}'::jsonb` would make every existing row match a "has flags" filter
and turn a small answer into every resume ever uploaded.

THE DEPLOY WINDOW. `docs/COMPLIANCE.md` records why migration 023 put consent in a new table
rather than as columns on `users`: migrations here are applied by hand, so there is always a
window where the code is live and the schema is not, and a new column on a table read by
`get_current_user` takes the whole application down for the length of it. That reasoning
does not apply here — `resume_files` is read on the resume and interview-setup paths only,
never on every request — but the window is real, so the column is nullable and every read of
it tolerates absence.

Revision ID: 027
Revises: 026
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resume_files",
        sa.Column("integrity_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # PARTIAL, on purpose. The index exists to answer one question — "which resumes did we
    # flag" — and that set is meant to stay small. Indexing the NULLs would be indexing
    # every resume in the product to find the handful that are not.
    op.create_index(
        "ix_resume_files_integrity_flagged",
        "resume_files",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("integrity_flags IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_resume_files_integrity_flagged", table_name="resume_files")
    op.drop_column("resume_files", "integrity_flags")
