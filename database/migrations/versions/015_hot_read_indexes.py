"""Composite indexes for the reads every page does, and dropping the ones they replace

WHY THIS EXISTS.

Every foreign key in this schema was already indexed — I checked, there were none missing.
What was missing is the SORT half of the three queries the app runs most, each of which is
"this user's rows, newest first":

    interview_sessions   WHERE user_id = ?    ORDER BY created_at DESC LIMIT 10
    reports              WHERE user_id = ?    ORDER BY created_at DESC
    answers              WHERE session_id = ? ORDER BY created_at

A single-column index on user_id serves the WHERE and leaves Postgres to sort the result.
EXPLAIN on the real query shape confirmed it, showing a Sort node above the scan for both
user-scoped queries. That is invisible for a user with four sessions and it is the whole
cost for a user with four hundred — and the answers query is worse than it looks, because
report generation reads EVERY answer in a session and a thousand candidates finishing an
interview in the same ten minutes is exactly what a campus drive is.

A composite (user_id, created_at DESC) index answers both halves and the Sort disappears.

AND THE PART THAT IS EASY TO GET WRONG: the old single-column indexes are then REDUNDANT
and are dropped. A btree on (a, b) already serves every query a btree on (a) does, because
`a` is the leading column — so keeping both means every INSERT and UPDATE maintains two
index entries where one would do. On the write-heaviest tables in the app that is a
throughput cost paid forever for nothing. Dropping a strictly-redundant leading-column
index is safe; dropping one that is not redundant is not, which is why only these three go
and each is named against the composite that replaces it.

`activity_logs` already had both — `(user_id)` and `(user_id, created_at)` — so its
redundant single-column index is dropped here too. That one predates this migration and
was presumably left behind when the composite was added.

DIRECTION MATTERS ON THE COMPOSITES. `created_at DESC` matches the ORDER BY exactly.
Postgres can scan a btree backwards, so an ASC index also avoids a sort for a DESC query —
but declaring the direction the queries actually use keeps the intent legible and costs
nothing.

`answers` is (session_id, created_at) ASC, because report generation reads a session's
answers in the order they were given, not in reverse.

CONCURRENTLY is deliberately NOT used. These tables are small today, Alembic runs each
migration in a transaction (which CREATE INDEX CONCURRENTLY cannot join), and the deploy
is a maintenance step rather than a live rolling change. If these tables ever grow to the
point where a brief lock matters, the index should be created by hand with CONCURRENTLY
outside a transaction and this migration stamped.

Revision ID: 015
Revises: 014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── The three composites the hot reads need ──────────────────────────────
    op.create_index(
        "ix_interview_sessions_user_created",
        "interview_sessions",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_reports_user_created",
        "reports",
        ["user_id", sa.text("created_at DESC")],
    )
    # ASC here: report generation replays a session's answers in the order they were
    # given, so this is the one of the three that is not "newest first".
    op.create_index(
        "ix_answers_session_created",
        "answers",
        ["session_id", "created_at"],
    )

    # ── The single-column indexes those replace ──────────────────────────────
    #
    # Each is the leading column of a composite created above (or, for activity_logs, of
    # one that already existed), so every query it served is still served. Keeping them
    # would mean maintaining a second index entry on every write for no read benefit.
    op.drop_index("ix_interview_sessions_user_id", table_name="interview_sessions")
    op.drop_index("ix_reports_user_id", table_name="reports")
    op.drop_index("ix_answers_session_id", table_name="answers")
    op.drop_index("ix_activity_logs_user_id", table_name="activity_logs")


def downgrade() -> None:
    # Recreate the single-column indexes first, so there is never a window with no index
    # on these columns at all.
    op.create_index("ix_activity_logs_user_id", "activity_logs", ["user_id"])
    op.create_index("ix_answers_session_id", "answers", ["session_id"])
    op.create_index("ix_reports_user_id", "reports", ["user_id"])
    op.create_index("ix_interview_sessions_user_id", "interview_sessions", ["user_id"])

    op.drop_index("ix_answers_session_created", table_name="answers")
    op.drop_index("ix_reports_user_created", table_name="reports")
    op.drop_index("ix_interview_sessions_user_created", table_name="interview_sessions")
