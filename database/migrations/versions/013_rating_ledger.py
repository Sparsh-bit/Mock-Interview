"""Interview Rating: the append-only ledger behind the cleared-rounds credential

WHY THIS EXISTS.

The product needed a reason to come back, and the model to copy is LeetCode: "412
solved, 180 medium" works as a credential because you cannot half-solve a problem,
so the number measures something and chasing it is the same act as improving.

A mock interview has no pass/fail — it has a score out of 100 — and a score that
only ever accumulates is a participation count. Twenty lazy rounds would read the
same as twenty good ones, and a number that can be farmed is a number nobody
respects, including the person farming it.

So this table backs two numbers with two different jobs:

  * CLEARED ROUNDS — monotonic. A COUNT over rows where `cleared` is true, split by
    tier. This is the showable credential, and it is the LeetCode analogue: a round
    clears when the report met that tier's bar (65 / 72 / 78 out of 100).

  * RATING — an Elo-style skill estimate, which can fall. This is the part that is
    hard to move, and the anti-farming property is not a rule bolted on: because
    the expectation rises with the rating, being far above a tier's difficulty means
    a perfect round in it pays almost nothing. Grinding the easy set stops paying by
    construction. The same maths is what keeps it fair — a strong candidate on a
    Panel round beats a high expectation and climbs fast.

DESIGN NOTES THAT MATTER IF YOU TOUCH THIS.

  * APPEND-ONLY, and there is deliberately NO `user_rating` table holding a current
    value. A rating is path-dependent — the result of a sequence, not of a set — and
    two stores of the same fact drift. The current rating is the newest row's
    `rating_after`; the credential is a COUNT. Both derived, so they cannot
    disagree, and both recomputable by replaying the ledger in order.

  * UNIQUE (session_id) is load-bearing, not hygiene. The writer runs when a report
    is generated and reports can be regenerated. Without this constraint a candidate
    could re-request a report to bank the same gain repeatedly, which is the cheapest
    possible exploit against the entire credential.

  * session_id is ON DELETE SET NULL, not CASCADE. If a session row is removed the
    round still happened. Cascading would let a candidate erase a bad round by
    deleting the session, which is the same exploit from the other direction.

  * `detail` (JSONB) holds the expectation, the raw result, the damper scale and the
    topic overlap behind `delta`. That is not debug residue: the UI has to be able to
    answer "why did that only give me two points", and a future change to the formula
    has to be auditable against what was actually shown at the time.

  * RLS is enabled with no policy, matching migration 012. The app connects as the
    table owner and bypasses RLS; this closes the table to the public anon key,
    which reaches Postgres through PostgREST where RLS is NOT bypassed. Without it
    the ledger would be world-readable and, worse, world-writable — anyone could
    insert themselves a rating.

Revision ID: 013
Revises: 012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rating_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL, not CASCADE — deleting a session must not delete the fact that
        # the round was rated. See the note above.
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("cleared", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("rating_after", sa.Integer(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("session_id", name="uq_rating_events_session"),
    )
    op.create_index("ix_rating_events_created_at", "rating_events", ["created_at"])
    op.create_index("ix_rating_events_kind", "rating_events", ["kind"])
    op.create_index("ix_rating_events_tier", "rating_events", ["tier"])
    # The hot read: "this user's newest event" (current rating) and "this user's
    # cleared rounds". Composite so both are index-only walks rather than a scan of
    # every row the user has ever produced.
    op.create_index(
        "ix_rating_events_user_created",
        "rating_events",
        ["user_id", sa.text("created_at DESC")],
    )
    # The leaderboard/percentile read: the newest rating_after per user. Kept as a
    # plain index on rating_after so a percentile can be computed without sorting
    # the whole table in memory.
    op.create_index("ix_rating_events_rating_after", "rating_events", ["rating_after"])

    op.execute("ALTER TABLE public.rating_events ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_rating_events_rating_after", table_name="rating_events")
    op.drop_index("ix_rating_events_user_created", table_name="rating_events")
    op.drop_index("ix_rating_events_tier", table_name="rating_events")
    op.drop_index("ix_rating_events_kind", table_name="rating_events")
    op.drop_index("ix_rating_events_created_at", table_name="rating_events")
    op.drop_table("rating_events")
