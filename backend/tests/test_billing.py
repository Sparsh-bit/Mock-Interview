"""
Plans, entitlement and payment verification — tests/test_billing.py

THE THINGS THAT FAIL SILENTLY ARE THE THINGS TESTED HARDEST HERE.

A broken API call fails the first time you try it. A missing signature check does not fail at
all — it works perfectly for every real payment and also for every forged one. Same for
idempotency: the happy path is indistinguishable from the bug until a customer who paid once
notices they were given three months.

Concurrency is the third. `count`, compare, `insert` passes every single-threaded test ever
written and still hands out two interviews to a double-clicked Start button.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from app.services.billing.plans import (
    FEATURES,
    PLANS,
    UNLIMITED,
    allowance_for,
    get_plan,
)
from app.services.billing.razorpay import (
    plan_from_payment,
    purchasable_plans,
    verify_signature,
)


class TestThePlanCatalogueIsCoherent:
    def test_every_plan_prices_every_metered_feature(self):
        # A feature missing from a plan silently resolves to 0, which reads to the user as
        # "your paid plan includes none of this".
        for plan in PLANS:
            for feature in FEATURES:
                assert feature in plan.allowances, f"{plan.id} does not price {feature}"

    def test_paid_plans_are_strictly_better_than_free(self):
        free = get_plan("free")
        for plan in PLANS:
            if plan.is_free:
                continue
            for feature in FEATURES:
                assert plan.allowances[feature] >= free.allowances[feature], (
                    f"{plan.id} gives less {feature} than Free"
                )

    def test_the_free_tier_matches_what_is_advertised(self):
        # 2 interviews, 1 GD, 5 communications. Pinned because these numbers appear in the
        # landing page, the pricing page and the paywall copy, and a change here that is not
        # a change there is a refund.
        free = get_plan("free")
        assert free.allowances == {"interview": 2, "gd": 1, "communication": 5}
        assert free.price_paise == 0

    def test_prices_rise_with_the_tier(self):
        paid = purchasable_plans()
        prices = [p.price_paise for p in paid]
        assert prices == sorted(prices), "plans are not ordered cheapest first"
        assert all(p > 0 for p in prices)

    def test_an_unknown_plan_falls_back_to_free_rather_than_raising(self):
        # A stale plan id in the database must not lock a user out mid-interview, and must
        # certainly not resolve to a paid tier.
        assert get_plan("enterprise-2019").id == "free"
        assert get_plan(None).id == "free"
        assert get_plan("").id == "free"

    def test_an_unknown_feature_grants_nothing(self):
        # Deliberately the opposite asymmetry from an unknown plan: metering something this
        # module has never heard of must not quietly become unlimited use.
        assert allowance_for("pro", "video_avatar") == 0
        assert allowance_for("free", "video_avatar") == 0

    def test_unlimited_is_a_number_so_comparisons_stay_simple(self):
        # Not None. Every call site does `used < allowance`, and a nullable allowance means
        # every one of them needs a None branch — the one that forgets charges a paid user.
        assert allowance_for("pro", "communication") >= UNLIMITED
        assert isinstance(allowance_for("pro", "communication"), int)


def _signed(body: dict, secret: str) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, sig


class TestWebhookSignatures:
    def test_a_correctly_signed_body_verifies(self):
        raw, sig = _signed({"event": "payment.captured"}, "shh")
        assert verify_signature(raw, sig, "shh")

    def test_a_tampered_body_does_not(self):
        raw, sig = _signed({"event": "payment.captured"}, "shh")
        assert not verify_signature(raw + b" ", sig, "shh")

    def test_the_wrong_secret_does_not(self):
        raw, sig = _signed({"event": "payment.captured"}, "shh")
        assert not verify_signature(raw, sig, "different")

    def test_a_missing_signature_is_a_failure_not_a_pass(self):
        # The branch an attacker aims for: "no signature supplied" must never be treated as
        # anything other than a rejection.
        raw, _ = _signed({"event": "payment.captured"}, "shh")
        assert not verify_signature(raw, "", "shh")

    def test_an_unset_webhook_secret_rejects_everything(self):
        # The correct closed default for a public URL. An empty secret must not mean
        # "verification disabled".
        raw, sig = _signed({"event": "payment.captured"}, "")
        assert not verify_signature(raw, sig, "")

    def test_re_serialised_json_does_not_verify(self):
        # Documents WHY the endpoint hashes the raw bytes. Key order and whitespace differ
        # after a parse/dump round trip, so hashing the re-serialised body rejects every
        # genuine webhook — a failure that looks like an attack rather than like a bug.
        body = {"event": "payment.captured", "b": 1, "a": 2}
        raw, sig = _signed(body, "shh")
        reserialised = json.dumps(json.loads(raw), sort_keys=True).encode()
        assert reserialised != raw
        assert not verify_signature(reserialised, sig, "shh")


def _payment(**over) -> dict:
    entity = {
        "id": "pay_ABC123",
        "status": "captured",
        "amount": get_plan("pro").price_paise,
        "notes": {"plan_id": "pro", "user_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7"},
    }
    entity.update(over)
    return {"event": "payment.captured", "payload": {"payment": {"entity": entity}}}


class TestReadingAPayment:
    def test_a_captured_payment_grants_the_plan(self):
        out = plan_from_payment(_payment())
        assert out is not None
        assert out.plan.id == "pro"
        assert out.payment_id == "pay_ABC123"

    def test_an_underpayment_grants_nothing(self):
        # `notes.plan_id` is client-supplied. Without checking the amount, ₹1 annotated
        # plan_id=pro buys Pro — the oldest bug in online payments.
        assert plan_from_payment(_payment(amount=100)) is None

    def test_an_overpayment_still_grants_the_plan(self):
        # Refusing money that was actually taken would be worse than accepting it.
        out = plan_from_payment(_payment(amount=get_plan("pro").price_paise * 2))
        assert out is not None and out.plan.id == "pro"

    def test_an_authorised_but_uncaptured_payment_grants_nothing(self):
        assert plan_from_payment(_payment(status="authorized")) is None
        assert plan_from_payment(_payment(status="failed")) is None

    def test_a_payment_naming_the_free_plan_grants_nothing(self):
        # Real money against the free plan id means the notes were wrong or tampered with.
        # A support ticket is the right outcome, not an unpaid upgrade.
        assert plan_from_payment(_payment(notes={"plan_id": "free", "user_id": "u"})) is None

    def test_a_payment_with_no_user_grants_nothing(self):
        assert plan_from_payment(_payment(notes={"plan_id": "pro"})) is None

    def test_an_unrelated_event_is_ignored_rather_than_erroring(self):
        # Razorpay sends many event types to one URL. An unrecognised one is routine, and the
        # endpoint answers 200 so it is not retried forever.
        assert plan_from_payment({"event": "refund.created", "payload": {}}) is None
        assert plan_from_payment({}) is None
