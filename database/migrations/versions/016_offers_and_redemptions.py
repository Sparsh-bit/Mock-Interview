"""offers and offer redemptions

Promo codes, festival offers and the private 100%-off code, plus the append-only record of
who used what.

THE UNIQUE INDEX ON (offer_id, user_id) IS THE FEATURE, not an optimisation. It is what makes
"one redemption per account" true under concurrency — two tabs, a double-clicked Apply, or a
retry storm cannot all succeed, because the second INSERT violates it. Application-level
checks have a window between the read and the write, and on something attached to money that
window gets found.

RLS IS ENABLED WITH NO POLICIES, matching every other table in this schema. The app connects
as the owner and bypasses RLS; the blanket deny is what keeps PostgREST shut, and PostgREST
matters here because the anon key ships in the browser bundle. An offers table readable
through it would hand every private code to anyone who opened dev tools.

Revision ID: 016
Revises: 015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

#: The tables this migration creates, named once.
#:
#: A module-level `_TABLES` list with the `public.` prefix below is not stylistic — it is the
#: shape tests/test_rls_coverage.py scans for, and that test is what stops a new table
#: reaching Supabase readable through PostgREST with the anon key that ships in the browser
#: bundle. Written first as an inline tuple, this migration's RLS was invisible to the scanner
#: and the test failed, which is exactly what it exists to do.
_TABLES: list[str] = ["offers", "offer_redemptions"]

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Stored uppercase so "diwali25" and "DIWALI25" cannot become two offers. The
        # uniqueness is on the stored form, and the service uppercases before it looks up.
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "applies_to",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        # The kill switch. Indexed with is_public below because the store filters on both.
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column(
            "requires_captcha", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        # SET NULL: removing an admin must not delete the record of an offer they created.
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_offers_code", "offers", ["code"])
    op.create_index("ix_offers_enabled", "offers", ["enabled"])
    op.create_index("ix_offers_public_enabled", "offers", ["is_public", "enabled", "ends_at"])

    op.create_table(
        "offer_redemptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "offer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("offers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_id", sa.String(64), nullable=False),
        sa.Column("original_paise", sa.Integer(), nullable=False),
        sa.Column("charged_paise", sa.Integer(), nullable=False),
        # NULL for a free grant, which never reaches the payment gateway at all.
        sa.Column("payment_ref", sa.String(128), nullable=True),
    )
    op.create_index("ix_offer_redemptions_created_at", "offer_redemptions", ["created_at"])
    op.create_index("ix_offer_redemptions_offer_id", "offer_redemptions", ["offer_id"])
    op.create_index("ix_offer_redemptions_user_id", "offer_redemptions", ["user_id"])
    op.create_index("ix_offer_redemptions_payment_ref", "offer_redemptions", ["payment_ref"])
    # THE RULE. Everything else about single-use is a message; this is the enforcement.
    op.create_index(
        "uq_offer_redemption_user",
        "offer_redemptions",
        ["offer_id", "user_id"],
        unique=True,
    )

    # Same posture as every other table here: enabled, no policies, so PostgREST is shut and
    # the app's owner connection is unaffected.
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("offer_redemptions")
    op.drop_table("offers")
