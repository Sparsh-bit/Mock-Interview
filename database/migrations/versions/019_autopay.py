"""auto top-up on user_plans

AUTO TOP-UP, NOT A SUBSCRIPTION. The product deliberately removed subscriptions — a student
betting ₹299 on using the app enough to justify it is the reason most of them never start.
This keeps "you buy what you use" and removes only the interruption: running out the evening
before a drive buys the next pack instead of showing a paywall.

Columns on `user_plans` rather than a new table, because there is exactly one autopay
configuration per account and `user_plans` is already the one-row-per-user table that
`consume` takes its lock on. A separate table would mean a second query, and a second query
means a window between reading the balance and reading whether to top it up.

NO CARD DATA. `autopay_token` is Razorpay's opaque reference to an instrument they hold; it
is useless anywhere else. A database leak does not become a card leak, and nothing in this
app ever sees a card number.

Revision ID: 019
Revises: 018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Off by default, and that is not merely a sensible default — money leaving an account
    # without the owner pressing anything is the fastest way to lose their trust, so it has
    # to be opted into rather than opted out of.
    op.add_column(
        "user_plans",
        sa.Column(
            "autopay_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("user_plans", sa.Column("autopay_item_id", sa.String(64), nullable=True))
    op.add_column("user_plans", sa.Column("autopay_token", sa.String(128), nullable=True))
    op.add_column(
        "user_plans", sa.Column("autopay_customer_id", sa.String(128), nullable=True)
    )
    op.add_column(
        "user_plans",
        sa.Column("autopay_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_plans",
        sa.Column(
            "autopay_failures", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )


def downgrade() -> None:
    for column in (
        "autopay_failures",
        "autopay_last_attempt_at",
        "autopay_customer_id",
        "autopay_token",
        "autopay_item_id",
        "autopay_enabled",
    ):
        op.drop_column("user_plans", column)
