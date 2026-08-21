"""
Every payment appears on the payer's own receipts, and on nobody else's — tests/test_receipts.py

WHY THIS FILE EXISTS. "Also the payment recipts and all the things also must work proeprly."
The endpoint was written, reviewed and believed correct — and had NO tests at all. Searching
the suite for "receipt" collected exactly one test, about ban strikes, matched on the word
"history". So the one endpoint that tells a candidate what they paid was resting entirely on
having been read carefully once.

The two things it can get wrong are not equally bad, and the tests are weighted accordingly.

  SHOWING TOO LITTLE is a support ticket. A candidate paid, cannot see it, and asks. Annoying,
  recoverable, and the money is still in the ledger.

  SHOWING SOMEBODY ELSE'S is a data breach involving payments. The endpoint takes no id and
  scopes on `current_user.user_id`, which is the correct design — and "the design is correct"
  is exactly the sentence that precedes an untested endpoint changing. `test_only_the_caller`
  is the one that must never be deleted.

DESIGN UNDER TEST, deliberately not changed by this file: receipts are derived from
`credit_events` rather than stored in a receipts table, so a receipt cannot disagree with what
the account actually received. That means these tests write ledger rows and read receipts —
which is the real path, not a mock of it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services.billing.credits import KIND_CONSUME, KIND_GRANT, KIND_PURCHASE

pytestmark = pytest.mark.asyncio


class _FakeUser:
    """Only `user_id` is read by the endpoint, so only `user_id` is supplied."""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        self.supabase_uid = str(user_id)
        self.email = f"{user_id}@example.test"


@pytest.fixture
async def ledger():
    """
    A session against the dev database, plus two users and a cleanup.

    Two users, always, because the assertion that matters most is that one of them cannot see
    the other's payments. A single-user fixture cannot express that, and a tenancy test that
    cannot fail is worse than none — it certifies the thing it does not check.
    """
    from sqlalchemy import delete
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import AsyncSessionFactory
    from app.models.billing import CreditEvent
    from app.models.user import User

    payer = uuid.uuid4()
    other = uuid.uuid4()
    try:
        async with AsyncSessionFactory() as db:
            # REAL USER ROWS, because credit_events.user_id is a foreign key and the first
            # version of this fixture invented ids. That FK is doing real work — a ledger
            # entry against a user who does not exist is money attributed to nobody — so the
            # fixture satisfies it rather than the test working around it.
            for uid in (payer, other):
                db.add(
                    User(
                        id=uid,
                        supabase_uid=str(uid),
                        email=f"receipts-{uid}@example.test",
                        is_active=True,
                        is_admin=False,
                    )
                )
            await db.commit()
            yield db, payer, other
            await db.execute(delete(CreditEvent).where(CreditEvent.user_id.in_([payer, other])))
            await db.execute(delete(User).where(User.id.in_([payer, other])))
            await db.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - environment, not behaviour
        pytest.skip(f"needs the dev Postgres: {exc}")


async def _event(db, user_id, **kw):
    from app.models.billing import CreditEvent

    row = CreditEvent(
        id=uuid.uuid4(),
        user_id=user_id,
        feature=kw.get("feature", "interview"),
        kind=kw.get("kind", KIND_PURCHASE),
        delta=kw.get("delta", 1),
        payment_ref=kw.get("payment_ref"),
        detail=kw.get("detail"),
        created_at=kw.get("created_at", datetime.now(UTC)),
    )
    db.add(row)
    await db.commit()
    return row


async def _receipts(db, user_id):
    from app.api.v1.billing import my_payments

    return (await my_payments(_FakeUser(user_id), db))["payments"]  # type: ignore[arg-type]


class TestWhatAPayerSees:
    async def test_a_purchase_shows_the_razorpay_id_as_the_receipt_number(self, ledger):
        # The payment id IS the receipt number on purpose: it is what Razorpay's dashboard and
        # their support both index by, so a prettier invented number would be one the candidate
        # could quote and nobody could look up.
        db, payer, _ = ledger
        await _event(
            db, payer,
            payment_ref="pay_TestAbc123",
            delta=5,
            detail={"item_id": "interview_5", "amount_paise": 24900},
        )
        [r] = await _receipts(db, payer)
        assert r["receipt"] == "pay_TestAbc123"
        assert r["paid"] is True
        assert r["kind"] == KIND_PURCHASE
        assert r["quantity"] == 5

    async def test_rupees_are_derived_from_paise_and_not_stored_twice(self, ledger):
        # Razorpay works in paise. A second stored rupee figure is a second version of the
        # truth about somebody's money.
        db, payer, _ = ledger
        await _event(db, payer, payment_ref="pay_X", detail={"amount_paise": 24900})
        [r] = await _receipts(db, payer)
        assert r["amount_paise"] == 24900
        assert r["amount_rupees"] == 249.0

    async def test_a_free_redemption_appears_as_a_grant_and_not_as_a_payment(self, ledger):
        """
        A candidate who redeemed a 100%-off code must see it as something they RECEIVED — not
        as a gap in their history, and not as money they paid. `paid` is what the UI keys on.
        """
        db, payer, _ = ledger
        row = await _event(db, payer, kind=KIND_GRANT, payment_ref=None, delta=1,
                           detail={"item_id": "interview_1", "offer": "LAUNCH100"})
        [r] = await _receipts(db, payer)
        assert r["kind"] == KIND_GRANT
        assert r["paid"] is False
        assert r["amount_rupees"] == 0
        assert r["offer"] == "LAUNCH100"
        # Still identifiable. A grant with no receipt string at all would be a row the
        # candidate cannot refer to when they ask about it.
        assert r["receipt"] == f"free-{str(row.id)[:8]}"

    async def test_spending_a_credit_is_not_a_receipt(self, ledger):
        # This is what you PAID, not what you spent. A consumption on the payments page reads
        # as a charge, and a candidate seeing twelve "payments" after one purchase will assume
        # they were billed twelve times.
        db, payer, _ = ledger
        await _event(db, payer, kind=KIND_CONSUME, delta=-1)
        assert await _receipts(db, payer) == []

    async def test_newest_first(self, ledger):
        db, payer, _ = ledger
        now = datetime.now(UTC)
        await _event(db, payer, payment_ref="older", created_at=now - timedelta(days=3))
        await _event(db, payer, payment_ref="newer", created_at=now)
        assert [r["receipt"] for r in await _receipts(db, payer)] == ["newer", "older"]

    async def test_an_unknown_item_id_still_produces_a_usable_row(self, ledger):
        """
        Item ids come from `plans.py` and a retired one must not blank a historical receipt.
        Somebody who bought a pack that no longer exists still paid for it, and a receipt that
        renders as an empty row is indistinguishable from a lost payment.
        """
        db, payer, _ = ledger
        await _event(db, payer, payment_ref="pay_old",
                     detail={"item_id": "pack_that_no_longer_exists", "amount_paise": 9900})
        [r] = await _receipts(db, payer)
        assert r["item_name"]
        assert r["amount_rupees"] == 99.0


class TestWhatAPayerMustNeverSee:
    async def test_only_the_caller(self, ledger):
        """
        THE ONE THAT MUST NEVER BE DELETED.

        The endpoint takes no id and scopes on the authenticated user, which is right. This
        asserts it, because "the design is correct" is the sentence that precedes an untested
        endpoint being changed — and the failure here is not a missing row, it is one
        candidate reading another candidate's payments.
        """
        db, payer, other = ledger
        await _event(db, payer, payment_ref="pay_mine")
        await _event(db, other, payment_ref="pay_theirs")

        mine = await _receipts(db, payer)
        theirs = await _receipts(db, other)

        assert [r["receipt"] for r in mine] == ["pay_mine"]
        assert [r["receipt"] for r in theirs] == ["pay_theirs"]

    async def test_an_account_with_no_payments_gets_an_empty_list_not_an_error(self, ledger):
        # A new candidate opening the billing page is the common case, and an exception there
        # would be reported as "billing is broken".
        db, _, other = ledger
        assert await _receipts(db, other) == []
