"""one device at a time — session ownership on users

Adds the two columns the User model already declares. They were added to the model when the
single-device feature was started and the migration was not written, which put the ORM and
the database out of step: SQLAlchemy emits `SELECT users.active_session_id …` on every
authenticated request, Postgres does not have the column, and every signed-in request 500s.

The startup drift check caught it and said so, which is what it is for:

    schema_drift_detected  users: ["model-only:active_session_id",
                                   "model-only:active_session_seen_at"]

BOTH COLUMNS ARE NULLABLE WITH NO DEFAULT, and that is what makes this safe to deploy ahead
of the enforcement. Every existing row gets NULL, which the resolver reads as "nobody owns
this account yet" — so the first request after deploy claims the slot silently rather than
locking anybody out of an account they are already using. A migration that logged everybody
out would be a worse outage than the one it fixes.

Revision ID: 020
Revises: 019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The Supabase `session_id` claim of the login that currently owns this account. Stable
    # across token refreshes and changed by a fresh sign-in, which is exactly the lifetime
    # "one device" needs: a second tab shares it, a phone does not.
    op.add_column("users", sa.Column("active_session_id", sa.String(128), nullable=True))
    # When a request last arrived on the owning session — the idle window that lets a new
    # sign-in take over an abandoned one rather than locking somebody out permanently.
    op.add_column(
        "users",
        sa.Column("active_session_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index: only rows that actually own a session are ever looked up by it, and on a
    # fresh deployment that is none of them. A full index would be almost entirely NULLs.
    op.create_index(
        "ix_users_active_session_id",
        "users",
        ["active_session_id"],
        postgresql_where=sa.text("active_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_active_session_id", table_name="users")
    op.drop_column("users", "active_session_seen_at")
    op.drop_column("users", "active_session_id")
