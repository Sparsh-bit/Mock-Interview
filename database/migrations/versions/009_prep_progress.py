"""track which roadmap subtopics a candidate has completed

The roadmap is only motivating if it remembers. Without this the road resets to
zero on every visit, which is worse than having no progress bar at all — it
actively tells someone their week of study did not happen.

Stored server-side rather than in localStorage on purpose: a candidate studies on
a laptop and checks their plan on a phone, and progress that lives in one
browser's storage is progress they lose the first time they switch. It is also the
only version that survives clearing site data before an interview.

One row per (user, subtopic). `subtopic_id` is the derived key from
services/prep/catalogue.subtopic_id() — "data_structures:trees-bst" — deliberately
NOT an index, so inserting a subtopic into the middle of a list cannot silently
reassign someone's completed items to different rows.

No foreign key to a subtopics table because there isn't one: subtopics live in
YAML, which is the right home for hand-maintained reference data. The trade-off is
that a renamed subtopic orphans its progress rows; they are harmless (nothing
reads them) and the alternative — a table, a migration and a seed per content
edit — costs more than it saves.

Revision ID: 009
Revises: 008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT to_regclass('public.prep_progress') IS NOT NULL").scalar():
        return

    op.create_table(
        "prep_progress",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Which company's plan this belongs to. The same subtopic can appear in
        # several companies' roadmaps, and ticking "Trees & BST" while preparing
        # for Amazon should also show as done on the TCS plan — so progress is
        # keyed on the SUBTOPIC, and company_slug is recorded for context only.
        sa.Column("company_slug", sa.String(64), nullable=True),
        sa.Column("subtopic_id", sa.String(128), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # A subtopic is done or not done — there is no "done twice". The unique
        # constraint makes completion idempotent at the database level, so a
        # double-tap on a phone cannot create a duplicate.
        sa.UniqueConstraint("user_id", "subtopic_id", name="uq_prep_progress_user_subtopic"),
    )


def downgrade() -> None:
    op.drop_table("prep_progress")
