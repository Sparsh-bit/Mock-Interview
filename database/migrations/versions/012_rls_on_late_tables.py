"""enable RLS on the two tables added after 002 that were missed

Supabase's security advisor flagged `public.prep_progress` and `public.ai_usage`
as CRITICAL: public tables with Row Level Security disabled. It is right, and the
hole was live rather than theoretical.

WHAT WAS ACTUALLY EXPLOITABLE. Supabase auto-exposes every table in `public`
through its PostgREST API, authenticated with the anon key — and the anon key is
not a secret: it ships inside the browser bundle to every visitor. With RLS off
there is nothing between that key and the table. Verified against production
before writing this, using only the anon key:

    POST   /rest/v1/ai_usage        -> 201   (inserted a fabricated $999.99 row)
    DELETE /rest/v1/ai_usage        -> 204   (delete permitted)
    POST   /rest/v1/prep_progress   -> 400   (rejected by a NOT NULL constraint
                                              on user_id, not by authorization)

So any visitor could read every user's AI spend, fabricate cost rows, or empty
the ledger. `prep_progress` was writable too — the 400 is a column constraint, and
a real user_id is discoverable. The probe row was deleted immediately; both tables
were empty at the time, so nothing leaked.

Every table from migration 002 was already protected — `answers` (89 rows),
`interview_sessions` (15), `users` (6), `reports` (7) and the rest all return zero
rows to the anon key while the service key sees them all. Migrations 003 and 004
remembered to extend the list. 009 (`prep_progress`) and 011 (`ai_usage`) did not.

RLS WITH NO POLICIES, matching 002 exactly. This looks wrong at first glance —
enabling RLS and then defining no policy denies everyone. That is the intent: the
backend does not go through PostgREST at all, it connects directly via asyncpg as
the table owner, and in Postgres the owner bypasses RLS unless FORCE ROW LEVEL
SECURITY is set. So a blanket deny closes the public API while leaving the
application untouched. Proven in production by the eighteen tables already doing
it.

Writing per-user policies instead would be worse here, not better: they would only
matter to a client we do not have, and every one would be a second copy of an
authorization rule that already lives in the API layer — two places to keep in
agreement, with the copy nobody exercises silently rotting.

Revision ID: 012
Revises: 011
"""

from __future__ import annotations

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None

#: Added after 002 and missed by it.
#:
#: prep_progress  migration 009 — which subtopics a candidate has completed.
#: ai_usage       migration 011 — per-user AI spend. Temporary; see
#:                TEMPORARY-token-counter.md. Enabling RLS on a table that is
#:                scheduled for deletion is still worth doing: it exists now, it
#:                is exposed now, and "we are going to delete it later" protects
#:                nobody in the meantime.
_TABLES = [
    "prep_progress",
    "ai_usage",
]


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
