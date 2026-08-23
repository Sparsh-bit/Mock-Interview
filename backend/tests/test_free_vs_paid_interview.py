"""
Which pot did this interview come out of? — tests/test_free_vs_paid_interview.py

THE PRODUCT RULE, as the owner stated it: "the free interview that we are giving ... the report
is payable ... the purchased interviews will not have the payment for the report generation".

So the report paywall needs to know, at report time, whether the interview that produced it was
free or paid for. THAT IS NOT ANSWERABLE FROM THE LEDGER AFTERWARDS. A consumption row is a
`-1` and says nothing about which pot it came from, and `remaining = trial_allowance + net` is a
single number that has already blended the trial allowance with purchased credit.

It IS knowable at consume time, and only there. Consumption draws on the trial allowance first —
that is exactly what `trial_allowance(feature) + net` means — so a consumption is free precisely
when fewer than `trial_allowance` have been consumed before it. `consume` now records that in
`credit_events.detail` as `paid_with`, which is JSONB and therefore needs no migration.

THE ONE RULE FOR THE READER, asserted at the bottom: an unknown value means DO NOT CHARGE. Every
interview taken before this deploy has no `paid_with`, and reading that as "free, so charge them"
would put a paywall in front of reports people had already earned.

## Why this file now tests `gd` rather than `interview`

`paid_with` records which pot a consumption came out of — the trial or something bought — and
it existed to decide whether a report was charged for. Interviews are paid outright now, so
`trial_allowance("interview")` is 0 and an interview can never be `paid_with="trial"`: there is
no free interview left to distinguish. The report paywall it fed has been removed with it.

The MECHANISM is generic and still live for group discussions and communication drills, which
still have a trial each, so the coverage moved to one of those rather than being deleted.
`paid_with` itself is kept as an audit field: it answers "was this person's session free or
paid" for a support or refund question that no other row can settle.
"""

from __future__ import annotations

import uuid
from collections import Counter

import pytest

from app.services.billing.credits import KIND_CONSUME, consume, grant
from app.services.billing.plans import TRIAL_ALLOWANCE, trial_allowance

pytestmark = pytest.mark.asyncio


def a_trialable_feature() -> str:
    """
    Any feature that still has a free trial.

    DERIVED, NOT NAMED, because these tests have now been re-pointed twice — from `interview`
    to `gd` when interviews became paid, and from `gd` to something else when group discussions
    did. The behaviour under test is the trial MECHANISM, which is generic; naming a feature
    couples every one of these tests to a pricing decision that has nothing to do with them.

    Raises if nothing is trialable any more, which is the honest outcome: the mechanism would
    then be unreachable and these tests would be asserting nothing. A loud failure is the signal
    to delete them, not to invent a fixture that keeps them green.
    """
    for feature, allowance in TRIAL_ALLOWANCE.items():
        if allowance > 0:
            return feature
    raise AssertionError(
        "no feature has a trial any more — the trial mechanism is unreachable, so these tests "
        "assert nothing and should be removed rather than propped up"
    )


@pytest.fixture
async def user():
    from sqlalchemy import delete
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import AsyncSessionFactory, engine
    from app.models.base import Base
    from app.models.billing import CreditEvent, UserPlan
    from app.models.user import User

    uid = uuid.uuid4()
    try:
        # test_integration.py drops the schema, so a fixture that assumes one silently SKIPS.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSessionFactory() as db:
            db.add(User(id=uid, supabase_uid=str(uid), email=f"pot-{uid}@example.test",
                        is_active=True, is_admin=False))
            await db.commit()
            yield db, uid
            await db.execute(delete(CreditEvent).where(CreditEvent.user_id == uid))
            await db.execute(delete(UserPlan).where(UserPlan.user_id == uid))
            await db.execute(delete(User).where(User.id == uid))
            await db.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - environment
        pytest.skip(f"needs the dev Postgres: {exc}")


# session_id is deliberately None throughout: these tests are about which POT a consumption
# came out of, and `credit_events.session_id` is a real foreign key, so inventing ids would test
# the constraint rather than the rule. A separate test in test_report_access covers the
# session-scoped read.
async def _paid_with(db, uid, feature: str | None = None) -> Counter[str | None]:
    """
    How many consumptions were marked each way. A COUNT, not a sequence, and deliberately.

    The first version of this returned an ordered list and was flaky under pytest-randomly. The
    reason is real rather than a test artefact: `created_at` is set per row from Python and two
    consumptions can land in the same microsecond, at which point the tie breaks on `id` — a
    uuid4, so the order is arbitrary. The ledger simply does not promise an intra-microsecond
    order, and a test that depends on one is asserting something the system never said.

    The RULE does not care about order anyway: it is "exactly `trial_allowance` of them are free
    and the rest are not". That is a multiset, so this counts.
    """
    from collections import Counter

    from sqlalchemy import select

    from app.models.billing import CreditEvent


    # DEFAULTED HERE, NOT IN THE SIGNATURE. A default is evaluated at import time and would
    # freeze whichever feature was trialable when this module loaded — and it is how this helper
    # came to name `gd`, which is now paid. `None` reaching the query silently matched nothing,
    # which reads as "the ledger wrote no row" rather than "the filter was wrong".
    feature = feature or a_trialable_feature()

    rows = (
        await db.execute(
            select(CreditEvent.detail).where(
                CreditEvent.user_id == uid,
                CreditEvent.kind == KIND_CONSUME,
                CreditEvent.feature == feature,
            )
        )
    ).scalars().all()
    return Counter((d or {}).get("paid_with") for d in rows)


class TestTheTrialIsSpentFirst:
    async def test_every_trial_interview_is_marked_trial(self, user):
        db, uid = user
        allowance = trial_allowance(a_trialable_feature())
        assert allowance > 0, "this test is meaningless without a free tier"

        for _ in range(allowance):
            await consume(db, uid, a_trialable_feature(), session_id=None)
            await db.commit()

        assert await _paid_with(db, uid) == {"trial": allowance}

    async def test_the_one_after_the_trial_is_marked_credit(self, user):
        """THE ASSERTION THE PRODUCT RULE RESTS ON."""
        db, uid = user
        allowance = trial_allowance(a_trialable_feature())

        for _ in range(allowance):
            await consume(db, uid, a_trialable_feature(), session_id=None)
            await db.commit()

        # They buy one, then use it.
        await grant(db, uid, a_trialable_feature(), 1, payment_ref="pay_TestPot")
        await db.commit()
        await consume(db, uid, a_trialable_feature(), session_id=None)
        await db.commit()

        assert await _paid_with(db, uid) == {"trial": allowance, "credit": 1}

    async def test_buying_early_does_not_make_the_trial_paid(self, user):
        """
        Somebody who buys credit before spending their free allowance still gets the free ones
        marked `trial`. The trial is spent first by construction — `remaining = trial + net` —
        and marking those as `credit` would hand away reports the rule says are payable.
        """
        db, uid = user
        await grant(db, uid, a_trialable_feature(), 5, payment_ref="pay_EarlyBird")
        await db.commit()

        allowance = trial_allowance(a_trialable_feature())
        for _ in range(allowance + 1):
            await consume(db, uid, a_trialable_feature(), session_id=None)
            await db.commit()

        assert await _paid_with(db, uid) == {"trial": allowance, "credit": 1}

    async def test_a_caller_s_own_detail_survives(self, user):
        # Call sites pass their own context in `detail`; the addition must merge, not replace.
        db, uid = user
        await consume(
            db, uid, a_trialable_feature(), session_id=None, detail={"track": "java-fse"}
        )
        await db.commit()

        from sqlalchemy import select

        from app.models.billing import CreditEvent

        detail = await db.scalar(
            select(CreditEvent.detail).where(CreditEvent.user_id == uid)
        )
        assert detail["track"] == "java-fse"
        assert detail["paid_with"] == "trial"

    async def test_features_are_counted_separately(self, user):
        """
        Spending one feature's trial must not change how another feature's use is marked.

        Demonstrated with a TRIALABLE feature and a PAID one, because only one feature has a
        trial left. That is the reachable version of the same rule: the paid feature's
        consumption is marked `credit` even though a trial was spent moments earlier on
        something else. Counting all consumptions together would mark it `trial` and give away
        a report — which is the bug this marker exists to prevent.
        """
        db, uid = user
        trialable = a_trialable_feature()
        paid = next(f for f, n in TRIAL_ALLOWANCE.items() if n == 0)

        for _ in range(trial_allowance(trialable)):
            await consume(db, uid, trialable, session_id=None)
            await db.commit()

        # Bought, then used. Its marker must not be borrowed from the other feature's trial.
        await grant(db, uid, paid, 1, payment_ref="pay_TestSeparate")
        await db.commit()
        await consume(db, uid, paid, session_id=None)
        await db.commit()

        from sqlalchemy import select

        from app.models.billing import CreditEvent

        detail = await db.scalar(
            select(CreditEvent.detail).where(
                CreditEvent.user_id == uid,
                CreditEvent.feature == paid,
                # The GRANT row for this feature has no `paid_with` and its detail is NULL, so
                # without this the query returns the purchase and the assertion below reads a
                # None. Only a consumption carries the marker.
                CreditEvent.kind == KIND_CONSUME,
            )
        )
        assert detail["paid_with"] == "credit"


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
class TestTheReaderMustFailOpen:
    def test_the_reason_the_marker_is_kept_is_stated_where_it_is_written(self):
        """
        WHAT THIS USED TO PIN, AND WHY IT CHANGED.

        It asserted the phrase "FAIL OPEN" in `consume`, guarding a rule that mattered while
        `report_access` read `paid_with` to decide whether to charge for a report: a row written
        before the field existed carries no marker, and reading absence as "free, therefore
        charge" would have paywalled every report already earned.

        That reader is gone. Interviews are paid outright, so there was nothing left to charge
        for and the paywall was removed with it. Grepping for a phrase that describes behaviour
        which no longer exists is ceremony, so what is asserted now is what is still true: the
        field is written, and the code says why it is worth keeping.
        """
        import inspect

        src = inspect.getsource(consume)
        assert "paid_with" in src
        assert "audit" in src.lower(), (
            "the reason paid_with is still written should be stated where it is written"
        )
