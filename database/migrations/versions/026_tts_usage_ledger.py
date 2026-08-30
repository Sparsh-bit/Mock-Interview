"""tts_usage — the durable record of what speech costs

WHAT THIS REPLACES, AND WHY A REDIS KEY WAS NOT ENOUGH. Speech has been metered since it
shipped, in `services/tts/spend.py`: an `INCRBYFLOAT` on a key named for the current UTC day,
with a 48-hour TTL. That is exactly the right shape for what it does — it is the brake read
by `_budget_room` before every synthesis, and it deliberately has no database dependency,
because a money guard that fails open when Postgres is slow is a money guard that does not
exist.

It is also unusable as a record:

  * one number for everybody — no user, no vendor, no speaker
  * two days of history, so any monthly figure reads as zero
  * a gauge, not a ledger: nothing to audit, nothing to reconcile against an invoice

So `GET /admin/revenue` could only ever report gross, and `plans.py` priced every item
against AI cost alone — while `services/tts/base.py` measures speech at up to twelve times
the AI cost of the same round on the wrong vendor. The margin was not incomplete, it was
wrong, and wrong in the flattering direction.

THE REDIS COUNTER IS NOT REMOVED AND MUST NOT BE. Brake and record are different jobs.

SHAPED LIKE `ai_usage` ON PURPOSE, down to `ON DELETE SET NULL` on the user. The two feed one
margin figure, and two answers to one question that are shaped differently are two things a
report has to reconcile before it can add them up.

CACHE HITS ARE ROWS. They cost nothing and they are written anyway, at zero, with the
character count of what would have been synthesised. `scripts/item_margin.py` shows the whole
margin gap between an interview and a group discussion is that an interview reads the same
twelve bank questions to every candidate while a GD's turns are unique — so the hit rate IS
the speech economics, and a ledger of misses alone could measure the bill and never measure
what reduces it. Hence the index on `cached`.

Revision ID: 026
Revises: 025
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

#: The shape tests/test_rls_coverage.py scans for. Migration 011 shipped `ai_usage` WITHOUT
#: RLS and the gap was found weeks later by Supabase's advisor, by which point that table was
#: provably insertable and deletable by any visitor holding the anon key — which ships in the
#: browser bundle. This is the same kind of table; it does not repeat that.
_TABLES: list[str] = ["tts_usage"]

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tts_usage",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        # A roster name from api/v1/gd.py or panel.py — product data, never the candidate.
        sa.Column("speaker", sa.String(64), nullable=False, server_default=""),
        sa.Column("characters", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cached", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        # NUMERIC so a SUM is exactly the sum of the rows and does not vary between runs when
        # Postgres picks a parallel aggregate plan. Same reasoning as ai_usage.cost_usd.
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        # SET NULL: removing an account must not erase the fact that money was spent.
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_tts_usage_user_id"),
            nullable=True,
        ),
    )
    op.create_index("ix_tts_usage_created_at", "tts_usage", ["created_at"])
    op.create_index("ix_tts_usage_provider", "tts_usage", ["provider"])
    op.create_index("ix_tts_usage_cached", "tts_usage", ["cached"])
    op.create_index("ix_tts_usage_user_id", "tts_usage", ["user_id"])

    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("tts_usage")
