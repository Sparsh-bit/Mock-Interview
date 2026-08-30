"""consent ledger, and making erasure lawful instead of merely complete

TWO CHANGES THAT BELONG TOGETHER, because the second is the reason the first can be
`ON DELETE SET NULL` without leaking anything.

1. `consent_events` — the DPDP §6 evidence ledger. Append-only: withdrawal is a new
   row with `granted = false`, never an update, because overwriting the history
   destroys the only proof that processing which ALREADY happened was lawful at the
   time. Carries the purpose, the notice version it was answered against, and when.

   A NEW TABLE RATHER THAN COLUMNS ON `users`, for the deployment reason 021 and 022
   both set out and models/user.py records having learned the hard way: migrations
   here are applied by hand against Supabase, so there is always a window where the
   code is live and the schema is not. A column on `users` is in every SELECT against
   the table `get_current_user` reads on EVERY authenticated request — so during that
   window the entire application 500s. A new table cannot do that.

2. Retention. `credit_events`, `offer_redemptions` and the new `consent_events` move
   from `ON DELETE CASCADE` to `ON DELETE SET NULL`, and gain a `retained_subject`
   column.

   WHY: `POST /users/me/delete` deletes the user row and lets the database cascade.
   `credit_events` and `offer_redemptions` are FINANCIAL RECORDS. The Companies Act,
   2013 §128(5) requires books of account for eight financial years, and DPDP §8(7)
   is explicit that erasure yields to a retention obligation under another law — so
   the old behaviour destroyed records the business is required to keep, silently, on
   a path the user triggers themselves.

   Destroying `offer_redemptions` was also a live abuse vector unrelated to law: that
   table's unique index is what stops a single-use code being redeemed twice, so
   deleting the row made delete-and-re-register a way to reuse any code.

   `retained_subject` holds a SALTED one-way digest of the user id, written by
   services/legal/retention.py in the same transaction as the delete. The surviving
   rows stay joinable to each other — which is what makes a refund dispute
   reconcilable — and to nobody. Amounts and dates remain; the person does not. An
   unsalted digest would be reversible by anyone holding the id, so it is salted with
   a server-side secret.

   `user_id` HAS TO BECOME NULLABLE for SET NULL to be possible at all. That is the
   only widening here, and it is safe in the pre-migration window in the same way the
   new table is: nothing writes NULL until the new code runs.

WHAT IS DELIBERATELY NOT RETAINED: the resume, its extracted text, the stored file,
answers, transcripts, scores and reports. Those are the sensitive data, no statute
requires keeping them, and they are cascaded away exactly as before. `audit_logs`
already had SET NULL and needs no change — it de-identifies itself and keeps the 180
days CERT-In asks for.

Revision ID: 023
Revises: 022
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


#: (table, existing FK constraint name). The names are Postgres's own defaults, which
#: is what earlier migrations created them as; `_swap_fk` asserts it found one rather
#: than silently leaving CASCADE in place.
_RETAINED = (
    ("credit_events", "credit_events_user_id_fkey"),
    ("offer_redemptions", "offer_redemptions_user_id_fkey"),
)


def upgrade() -> None:
    # ── 1. The consent ledger ────────────────────────────────────────────────
    op.create_table(
        "consent_events",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("retained_subject", sa.String(length=64), nullable=True),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("notice_version", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("detail", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_consent_events_user_id", "consent_events", ["user_id"])
    op.create_index("ix_consent_events_purpose", "consent_events", ["purpose"])
    op.create_index("ix_consent_events_created_at", "consent_events", ["created_at"])
    op.create_index(
        "ix_consent_events_retained_subject", "consent_events", ["retained_subject"]
    )
    # The hot read: this person's newest answer for one purpose. Runs on the
    # resume-upload path, before the file is accepted.
    op.create_index(
        "ix_consent_events_user_purpose",
        "consent_events",
        ["user_id", "purpose", "created_at"],
    )

    # ROW LEVEL SECURITY, BECAUSE SUPABASE EXPOSES EVERY PUBLIC TABLE. A new table in
    # `public` is reachable through PostgREST with the anon key the moment it exists,
    # and this one records who agreed to what. test_rls_coverage.py fails the build on
    # a table that skips this.
    op.execute("ALTER TABLE consent_events ENABLE ROW LEVEL SECURITY")

    # ── 2. Retention ─────────────────────────────────────────────────────────
    for table, constraint in _RETAINED:
        op.add_column(table, sa.Column("retained_subject", sa.String(length=64), nullable=True))
        op.create_index(f"ix_{table}_retained_subject", table, ["retained_subject"])
        op.alter_column(table, "user_id", existing_type=sa.UUID(as_uuid=True), nullable=True)
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, "users", ["user_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    """
    Reversible, with one honest caveat stated rather than hidden.

    Going back to CASCADE and NOT NULL requires there to be no de-identified rows —
    a row whose account is already gone has a NULL user_id that NOT NULL cannot
    accept. Those rows are DELETED on downgrade, which is a real loss of the
    financial records this migration exists to preserve. It is the only way back to
    the old shape, and it is why the downgrade should be used to unwind a bad deploy
    within minutes, not to reverse the policy weeks later.
    """
    for table, constraint in reversed(_RETAINED):
        op.execute(f"DELETE FROM {table} WHERE user_id IS NULL")  # noqa: S608 — fixed literals
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        op.alter_column(table, "user_id", existing_type=sa.UUID(as_uuid=True), nullable=False)
        op.drop_index(f"ix_{table}_retained_subject", table_name=table)
        op.drop_column(table, "retained_subject")

    op.drop_index("ix_consent_events_user_purpose", table_name="consent_events")
    op.drop_index("ix_consent_events_retained_subject", table_name="consent_events")
    op.drop_index("ix_consent_events_created_at", table_name="consent_events")
    op.drop_index("ix_consent_events_purpose", table_name="consent_events")
    op.drop_index("ix_consent_events_user_id", table_name="consent_events")
    op.drop_table("consent_events")
