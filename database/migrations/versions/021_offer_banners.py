"""a promo banner image for a coupon code

Adds `offer_banners`: one optional image per offer, shown on the dashboard and linking to the
pricing page's apply-a-code box.

A SEPARATE TABLE RATHER THAN COLUMNS ON `offers`, AND THE REASON IS DEPLOYMENT SHAPE.
Migrations on this project are run BY HAND against Supabase (see docs/DEPLOY.md) — nothing
applies them on deploy. So there is always a window where the new code is live and the schema
is not, and the only question that matters is what breaks during it.

Columns on `offers` would mean SQLAlchemy emitting `SELECT offers.banner_url …` on every read
of that table — the pricing page, the quote, checkout, redemption — so the entire paid path
would 500 until someone remembered to run this. A new table cannot do that: nothing existing
selects from it, so before the migration the banner feature simply has nothing to show, and
every money path carries on exactly as it did. The read is guarded on top of that, so even a
direct query degrades to "no banner" instead of erroring.

ONE BANNER PER OFFER, enforced by a UNIQUE constraint on `offer_id` rather than by the upload
endpoint checking first. Re-uploading replaces, and two admins uploading at once cannot leave
two rows where the reader expects one.

CASCADE ON DELETE, because a banner for a deleted offer is unreachable content advertising a
code that no longer exists. The stored FILE is deleted by the endpoint; this only guarantees
the row cannot outlive its offer.

THE DIMENSIONS ARE STORED, not just the URL. They are what the admin list shows when it says
whether an image matches the required ratio, and keeping them means that check never has to
re-download the image to answer.

Revision ID: 021
Revises: 020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

#: The tables this migration protects. A LIST NAMED `_TABLES`, matching every other migration
#: here, because tests/test_rls_coverage.py scans for exactly that shape to prove each model
#: table is covered — an inline tuple is invisible to it, and an uncovered table fails silently
#: in the direction of being exposed.
_TABLES = ["offer_banners"]

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offer_banners",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "offer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("offers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Where the file lives in the bucket. Kept so the file can be deleted when the banner
        # is replaced or removed — a URL alone cannot be turned back into a storage path
        # reliably once the bucket's public URL format changes.
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        # Alt text is NOT NULL because a banner is a link: with no accessible name, a screen
        # reader announces an unlabelled link to the pricing page.
        sa.Column("alt_text", sa.String(160), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # SAME POSTURE AS EVERY OTHER TABLE HERE: RLS enabled with no policies, so PostgREST — the
    # path the public anon key reaches — is shut, while the app's own owner connection is
    # unaffected. Pinned by tests/test_rls_coverage.py, which fails on any model table that no
    # migration protects; it caught this one before it shipped.
    #
    # The banner IMAGE is deliberately public (a public storage bucket, so an <img> needs no
    # signed URL). This row is not the image: it also carries the storage path, who uploaded
    # it and which offer it belongs to, and none of that has any reason to be readable by an
    # anonymous client.
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("offer_banners")
