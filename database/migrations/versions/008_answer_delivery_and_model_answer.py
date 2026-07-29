"""per-answer delivery detail and cached model answers

Two columns on `answers`, both for the detailed analysis view:

  delivery       The client-measured delivery for THIS answer, including the
                 position of every pause. Delivery metrics were already sent per
                 answer, but the orchestrator only accumulated totals onto the
                 session — so "16 filler words, 4 pauses" survived while *where*
                 the candidate hesitated was discarded at the point of submission.
                 Showing someone their own answer with the pauses marked is not
                 possible from a total, so the detail is now kept.

  model_answer   The full coaching payload for this answer — the model answer
                 plus what was missing, the key points, and a verdict line —
                 generated on demand and cached here.

                 JSONB rather than TEXT so the whole payload survives. Storing
                 only the answer text would show rich coaching on first generation
                 and then silently lose it on reload, or force a second billed call
                 to rebuild it.

                 Cached because it is a billed AI call and the detailed view is
                 re-read freely. Stored per ANSWER, not per question, because it is
                 written against what this candidate actually said.

Both nullable: every existing answer predates them, and NULL is the honest value
for "never captured" / "not generated yet".

Revision ID: 008
Revises: 007
"""

from __future__ import annotations

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("delivery", "JSONB"),
    ("model_answer", "JSONB"),
    ("model_answer_generated_at", "TIMESTAMPTZ"),
)


def upgrade() -> None:
    bind = op.get_bind()

    if not bind.exec_driver_sql(
        "SELECT to_regclass('public.answers') IS NOT NULL"
    ).scalar():
        return

    for name, ddl in _COLUMNS:
        op.execute(f"ALTER TABLE answers ADD COLUMN IF NOT EXISTS {name} {ddl}")


def downgrade() -> None:
    for name, _ddl in _COLUMNS:
        op.execute(f"ALTER TABLE answers DROP COLUMN IF EXISTS {name}")
