"""
Referrals: does the credit arrive when it should — tests/test_referrals.py

The abuse cases live next door in test_pentest_referrals.py. This file is the other half:
that a legitimate referral actually pays, that it pays ONCE, that it pays through the ledger
rather than around it, and that the timing is the one the design says it is.

WHY THESE NEED A REAL DATABASE. Almost every guarantee here is a database guarantee — a
unique index, a check constraint, a row lock, an append-only ledger. A test that patches the
session proves a function was called; only real rows prove the rule holds.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models.billing import CreditEvent, Referral, ReferralCode
from app.services.billing import referrals
from app.services.billing.credits import (
    KIND_CONSUME,
    KIND_GRANT,
    consume,
    get_balance,
    grant,
)
from app.services.billing.plans import REFERRAL_REWARD


async def _schema():
    from app.db.session import engine
    from app.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _make_user(*, admin: bool = False) -> uuid.UUID:
    """A real, committed account. Referral rules are about accounts, so these must exist."""
    from app.db.session import AsyncSessionFactory
    from app.models.user import User

    await _schema()
    uid = uuid.uuid4()
    async with AsyncSessionFactory() as db:
        db.add(
            User(
                id=uid,
                supabase_uid=str(uid),
                email=f"ref-{uid}@example.test",
                is_active=True,
                is_admin=admin,
            )
        )
        await db.commit()
    return uid


async def _code_of(user_id: uuid.UUID) -> str:
    from app.db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        row = await referrals.code_for(db, user_id)
        await db.commit()
        return row.code


async def _claim(referred: uuid.UUID, code: str) -> None:
    from app.db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        await referrals.claim(db, user_id=referred, code=code)
        await db.commit()


async def _buy_and_use(user_id: uuid.UUID, feature: str = "interview") -> None:
    """
    Buy one of `feature`, then consume it — the qualifying event.

    Two transactions on purpose: a purchase and a consumption are two requests in the
    product, and collapsing them here would test a sequence that never happens.
    """
    from app.db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        await grant(
            db,
            user_id,
            feature,
            1,
            payment_ref=f"pay_{uuid.uuid4().hex[:12]}",
        )
        await db.commit()
    async with AsyncSessionFactory() as db:
        await consume(db, user_id, feature)
        await db.commit()


async def _read_balance(user_id: uuid.UUID):
    from app.db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        balance = await get_balance(db, user_id)
        await db.commit()
        return balance


async def _grant_rows(user_id: uuid.UUID) -> list[CreditEvent]:
    from app.db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        return list(
            (
                await db.execute(
                    select(CreditEvent).where(
                        CreditEvent.user_id == user_id, CreditEvent.kind == KIND_GRANT
                    )
                )
            ).scalars()
        )


async def _referral_row(referred: uuid.UUID) -> Referral | None:
    from app.db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        return await db.scalar(
            select(Referral).where(Referral.referred_user_id == referred)
        )


@pytest.mark.asyncio
class TestTheCode:
    async def test_every_account_gets_one_and_it_is_stable(self):
        user = await _make_user()
        first = await _code_of(user)
        second = await _code_of(user)
        assert first == second, (
            "a regenerated code invalidates every link already shared — the one thing a "
            "referral link must never do"
        )

    async def test_two_accounts_do_not_share_a_code(self):
        a, b = await _make_user(), await _make_user()
        assert await _code_of(a) != await _code_of(b)

    async def test_the_alphabet_excludes_confusable_characters(self):
        """
        A code is read off one phone screen and typed into another. A mistyped code is
        indistinguishable from an invalid one, so the candidate concludes the feature is
        broken rather than that they misread an O for a 0.
        """
        code = await _code_of(await _make_user())
        for confusable in "OIL01S5U":
            assert confusable not in code, f"{confusable!r} is confusable and is in {code!r}"

    async def test_a_typed_code_survives_whitespace_and_case(self):
        """
        Pasted from a screenshot or a wrapped chat message. `.strip()` alone is not enough —
        a newline can land INSIDE the value, which this repo has already been bitten by once
        in TTS_VOICE_IDS.
        """
        code = await _code_of(await _make_user())
        assert referrals.normalise(f"  {code.lower()}  ") == code
        assert referrals.normalise(f"{code[:4]}\n{code[4:]}") == code


@pytest.mark.asyncio
class TestNothingIsGrantedBeforeRealUsage:
    """
    The gate the whole design rests on. Every assertion here is a thing that must NOT happen.
    """

    async def test_claiming_grants_nothing_to_either_side(self):
        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))

        assert await _grant_rows(referrer) == []
        assert await _grant_rows(referred) == []
        row = await _referral_row(referred)
        assert row is not None and row.qualified_at is None

    async def test_signing_up_and_doing_nothing_grants_nothing(self):
        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))
        # The referrer loads their dashboard repeatedly. Settlement runs every time and must
        # find nothing to settle.
        for _ in range(3):
            await _read_balance(referrer)
        assert await _grant_rows(referrer) == []

    async def test_burning_the_free_trial_does_not_qualify(self):
        """
        THE ATTACK THIS CLOSES IS THE CHEAPEST ONE AVAILABLE. `TRIAL_ALLOWANCE` includes one
        free communication drill, so if "first use" qualified, a farm costs one throwaway
        email address and about $0.025 of our AI per account — and returns a reward on BOTH
        sides. It would be profitable on day one.

        `consume` records `paid_with` on every row, and only "credit" qualifies.
        """
        from app.db.session import AsyncSessionFactory

        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))

        async with AsyncSessionFactory() as db:
            event = await consume(db, referred, "communication")
            await db.commit()
        assert event is not None and event.detail["paid_with"] == "trial"

        assert await _grant_rows(referred) == []
        await _read_balance(referrer)
        assert await _grant_rows(referrer) == []
        row = await _referral_row(referred)
        assert row is not None and row.qualified_at is None

    async def test_buying_without_using_does_not_qualify(self):
        """
        A purchase can be charged back. Requiring the CONSUMPTION means the product was
        actually delivered before anything is given away.
        """
        from app.db.session import AsyncSessionFactory

        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))

        async with AsyncSessionFactory() as db:
            await grant(db, referred, "interview", 1, payment_ref=f"pay_{uuid.uuid4().hex[:8]}")
            await db.commit()

        row = await _referral_row(referred)
        assert row is not None and row.qualified_at is None
        await _read_balance(referrer)
        assert await _grant_rows(referrer) == []


@pytest.mark.asyncio
class TestItPaysWhenItShould:
    async def test_a_paid_consumption_qualifies_and_pays_the_new_account_immediately(self):
        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))
        await _buy_and_use(referred)

        row = await _referral_row(referred)
        assert row is not None and row.qualified_at is not None
        assert row.referred_granted_at is not None

        grants = await _grant_rows(referred)
        assert len(grants) == 1
        assert grants[0].feature == REFERRAL_REWARD.feature
        assert grants[0].delta == REFERRAL_REWARD.quantity
        assert grants[0].detail["reason"] == "referral_referred"

    async def test_the_referrer_is_paid_the_next_time_they_look_at_their_balance(self):
        """
        The two grants are written by two transactions on purpose — see the module docstring
        in services/billing/referrals.py. The consequence, pinned here so it is a documented
        behaviour rather than a surprise: the referrer's reward exists from the moment they
        next touch their own balance, and not before.
        """
        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))
        await _buy_and_use(referred)

        assert await _grant_rows(referrer) == [], "not paid inside the other user's request"

        await _read_balance(referrer)
        grants = await _grant_rows(referrer)
        assert len(grants) == 1
        assert grants[0].detail["reason"] == "referral_referrer"

    async def test_the_referrers_reward_is_spendable_on_the_request_that_settles_it(self):
        """
        Settlement runs inside `consume` BEFORE the balance is read. The alternative ordering
        refuses somebody who does have credit — a paywall in front of something they earned.
        """
        from app.db.session import AsyncSessionFactory

        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))
        await _buy_and_use(referred)

        # The referrer has never bought anything and has spent their trial drill already.
        async with AsyncSessionFactory() as db:
            await consume(db, referrer, "communication")
            await db.commit()

        # This second one can only succeed on the referral reward.
        async with AsyncSessionFactory() as db:
            event = await consume(db, referrer, REFERRAL_REWARD.feature)
            await db.commit()
        assert event is not None

    async def test_the_reward_shows_up_in_the_balance_both_sides_read(self):
        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))
        await _buy_and_use(referred)

        for user in (referrer, referred):
            balance = await _read_balance(user)
            reward = next(
                f for f in balance.features if f.feature == REFERRAL_REWARD.feature
            )
            assert reward.remaining >= REFERRAL_REWARD.quantity, (
                f"{user} earned a referral reward that their balance does not show"
            )

    async def test_it_is_a_ledger_grant_and_never_a_balance_mutation(self):
        """
        There is no balance to mutate — a balance is a SUM over `credit_events` — so this
        pins the shape of what was written: a positive `grant` row, correctly signed, on the
        append-only ledger, with a reason attached.
        """
        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))
        await _buy_and_use(referred)
        await _read_balance(referrer)

        for user, reason in ((referrer, "referral_referrer"), (referred, "referral_referred")):
            rows = await _grant_rows(user)
            assert len(rows) == 1
            row = rows[0]
            assert row.kind == KIND_GRANT
            assert row.delta > 0
            assert row.detail["reason"] == reason
            assert row.payment_ref.startswith(f"{referrals.REF_PREFIX}:")

    async def test_a_second_paid_consumption_pays_nothing_more(self):
        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))
        await _buy_and_use(referred)
        await _buy_and_use(referred)
        await _read_balance(referrer)
        await _read_balance(referrer)

        assert len(await _grant_rows(referred)) == 1
        assert len(await _grant_rows(referrer)) == 1

    async def test_one_referrer_can_be_paid_for_several_people(self):
        referrer = await _make_user()
        code = await _code_of(referrer)
        for _ in range(3):
            referred = await _make_user()
            await _claim(referred, code)
            await _buy_and_use(referred)
        await _read_balance(referrer)
        assert len(await _grant_rows(referrer)) == 3


@pytest.mark.asyncio
class TestTheStatusPage:
    async def test_it_counts_claimed_qualified_and_rewarded_separately(self):
        from app.db.session import AsyncSessionFactory

        referrer = await _make_user()
        code = await _code_of(referrer)

        # One who claimed and did nothing, one who paid and used.
        idle = await _make_user()
        await _claim(idle, code)
        active = await _make_user()
        await _claim(active, code)
        await _buy_and_use(active)

        async with AsyncSessionFactory() as db:
            status = await referrals.status_for(db, referrer)
            await db.commit()
        assert status.claimed == 2
        assert status.qualified == 1
        # Not yet settled: reading the status is not reading the balance.
        assert status.rewarded == 0

        await _read_balance(referrer)
        async with AsyncSessionFactory() as db:
            status = await referrals.status_for(db, referrer)
            await db.commit()
        assert status.rewarded == 1

    async def test_it_never_names_anybody(self):
        """
        The referrer has no business knowing which email addresses signed up under their
        code. A growth feature that discloses that is a disclosure.
        """
        from dataclasses import fields

        names = {f.name for f in fields(referrals.ReferralStatus)}
        for leak in ("emails", "users", "user_ids", "referred_users", "names"):
            assert leak not in names
        assert all(
            not name.endswith("_email") and not name.endswith("_id") for name in names
        ), names

    async def test_it_reports_the_reward_from_plans_rather_than_a_local_constant(self):
        from app.db.session import AsyncSessionFactory

        async with AsyncSessionFactory() as db:
            status = await referrals.status_for(db, await _make_user())
            await db.commit()
        assert status.reward_feature == REFERRAL_REWARD.feature
        assert status.reward_quantity == REFERRAL_REWARD.quantity


@pytest.mark.asyncio
class TestQualificationHelper:
    async def test_it_agrees_with_what_actually_qualified(self):
        from app.db.session import AsyncSessionFactory

        user = await _make_user()
        async with AsyncSessionFactory() as db:
            assert await referrals.qualifies_now(db, user) is False

        # A trial consumption does not count.
        async with AsyncSessionFactory() as db:
            await consume(db, user, "communication")
            await db.commit()
        async with AsyncSessionFactory() as db:
            assert await referrals.qualifies_now(db, user) is False

        await _buy_and_use(user)
        async with AsyncSessionFactory() as db:
            assert await referrals.qualifies_now(db, user) is True


@pytest.mark.asyncio
class TestConsumptionIsUnaffected:
    """
    The referral hook lives inside `consume`, the single most important function in the
    product. It must not change what that function does for the overwhelming majority of
    users, who were never referred by anybody.
    """

    async def test_an_unreferred_user_consumes_exactly_as_before(self):
        from app.db.session import AsyncSessionFactory

        user = await _make_user()
        await _buy_and_use(user, "interview")

        async with AsyncSessionFactory() as db:
            consumed = await db.scalar(
                select(func.count())
                .select_from(CreditEvent)
                .where(CreditEvent.user_id == user, CreditEvent.kind == KIND_CONSUME)
            )
            granted = await db.scalar(
                select(func.count())
                .select_from(CreditEvent)
                .where(CreditEvent.user_id == user, CreditEvent.kind == KIND_GRANT)
            )
        assert consumed == 1
        assert granted == 0, "an unreferred user must never be granted anything"

    async def test_an_admin_consumption_writes_no_row_and_qualifies_nothing(self):
        """
        Admins are unmetered, so `consume` returns before writing anything. A referral that
        qualified on an admin's usage would be entitlement minted from a row that does not
        exist.
        """
        from app.db.session import AsyncSessionFactory

        referrer = await _make_user()
        admin = await _make_user(admin=True)
        await _claim(admin, await _code_of(referrer))

        async with AsyncSessionFactory() as db:
            assert await consume(db, admin, "interview") is None
            await db.commit()

        row = await _referral_row(admin)
        assert row is not None and row.qualified_at is None


@pytest.mark.asyncio
class TestErasureKeepsTheRecord:
    async def test_the_row_survives_and_is_de_identified_from_either_side(self):
        """
        A referral row explains a `credit_events` grant that no payment paid for. Deleting it
        on erasure would leave an unexplainable grant in the books; keeping it with the id in
        place would not be erasure. So: kept, stamped, and un-joinable to a person.
        """
        from app.db.session import AsyncSessionFactory
        from app.services.legal.retention import (
            deidentify_retained_records,
            subject_digest,
        )

        referrer, referred = await _make_user(), await _make_user()
        await _claim(referred, await _code_of(referrer))

        async with AsyncSessionFactory() as db:
            counts = await deidentify_retained_records(db, referrer)
            await db.commit()
        assert counts["referrals"] == 1

        async with AsyncSessionFactory() as db:
            row = await db.scalar(
                select(Referral).where(Referral.referred_user_id == referred)
            )
            assert row is not None
            await db.refresh(row, ["retained_subject"])
            assert row.retained_subject == subject_digest(referrer)

    async def test_the_code_itself_does_not_outlive_its_owner(self):
        """
        CASCADE on `referral_codes.user_id`, unlike every other user reference in the billing
        schema. A code is a live credential, not a financial record: one that outlived its
        account would keep crediting somebody who is not there.
        """
        from app.db.session import AsyncSessionFactory
        from app.models.user import User

        user = await _make_user()
        code = await _code_of(user)

        async with AsyncSessionFactory() as db:
            await db.delete(await db.get(User, user))
            await db.commit()

        async with AsyncSessionFactory() as db:
            assert await db.scalar(
                select(ReferralCode).where(ReferralCode.code == code)
            ) is None


@pytest.mark.asyncio
class TestTheRewardIsEconomicallySane:
    """
    Not a style check. `scripts/item_margin.py` exists because the obvious reward — one free
    interview each — costs more to hand over than the cheapest qualifying purchase earns.
    """

    async def test_the_reward_is_defined_once_in_plans(self):
        from pathlib import Path

        import app.services.billing.referrals as service_source

        source = Path(service_source.__file__).read_text()
        assert "REFERRAL_REWARD" in source
        for hardcoded in ('"interview", 1', "feature=\"interview\"", "quantity=2"):
            assert hardcoded not in source, (
                f"{hardcoded!r} in the referral service is a second place an allowance is "
                "decided — plans.py is the only one"
            )

    async def test_the_reward_grants_a_feature_that_actually_exists(self):
        from app.services.billing.plans import FEATURES

        assert REFERRAL_REWARD.feature in FEATURES
        assert REFERRAL_REWARD.quantity >= 1

    async def test_a_qualified_referral_pays_out_less_than_the_cheapest_purchase_earns(self):
        """
        The go/no-go on the reward size, computed from the same cost model
        `scripts/item_margin.py` reports. A referral only pays out after the referred account
        has BOUGHT and CONSUMED something; the cheapest thing that can have been is the
        ₹19 drill. If two rewards cost more than that purchase nets, every referral whose
        first purchase was a drill loses money.
        """
        from app.services.billing.plans import get_item
        from scripts.item_margin import (
            _INR_PER_USD,
            _MEASURED_AI_COST_PER_ITEM,
            _PAYMENT_FEE_RATE,
            SPEECH,
            vendor_scenarios,
        )

        fish = next(s for s in vendor_scenarios() if s.name == "fish")

        def cost(feature: str) -> float:
            return (
                _MEASURED_AI_COST_PER_ITEM[feature]
                + SPEECH[feature].steady_chars * fish.usd_per_char
            )

        cheapest = get_item("communication_1")
        revenue = cheapest.price_paise / 100 / _INR_PER_USD
        net = revenue - revenue * _PAYMENT_FEE_RATE - cost(cheapest.feature)

        payout = 2 * REFERRAL_REWARD.quantity * cost(REFERRAL_REWARD.feature)
        assert payout < net, (
            f"a referral pays out ${payout:.4f} and the cheapest qualifying purchase nets "
            f"${net:.4f}. Every referral whose first purchase is a drill loses money. "
            "Change REFERRAL_REWARD in plans.py, or change the qualifying condition."
        )
