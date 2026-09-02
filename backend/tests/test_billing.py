"""
The catalogue and payment verification — tests/test_billing.py

THE THINGS THAT FAIL SILENTLY ARE THE THINGS TESTED HARDEST HERE.

A broken API call fails the first time you try it. A missing signature check does not fail
at all — it works perfectly for every real payment and also for every forged one. Same for
idempotency: the happy path is indistinguishable from the bug until a customer who paid for
five interviews notices they were given fifteen.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from app.services.billing.plans import (
    FEATURES,
    ITEMS,
    TRIAL_ALLOWANCE,
    get_item,
    items_for,
    trial_allowance,
)
from app.services.billing.razorpay import items_from_payment, verify_signature


class TestTheTrial:
    def test_only_communication_drills_are_trialable(self):
        """
        INTERVIEWS AND GROUP DISCUSSIONS ARE BOTH ZERO ON PURPOSE. Set by the owner in two
        steps: every interview is bought, then "make the gd also payment and not free for
        anyone only for the admins". Admins were already unmetered — `consume` returns before
        charging an operator account — so that half needed no change.

        DECK REVIEWS JOINED AT ZERO. A vision pass over a dozen rendered slides plus a DEEP
        judging call costs nearer an interview than a drill, so it is priced like one. The
        test's name still holds: communication remains the only trialable feature.

        Pinned as an exact dict because it is a pricing decision and every one of these numbers
        is revenue: a stray 1 gives a product away to every new account, and a stray 0 on
        communication drills silently paywalls the last thing a candidate can try for free.
        That is also why this is not loosened to "communication is the only non-zero entry" —
        a new feature must break this test and be decided, not inherit a default.
        """
        assert TRIAL_ALLOWANCE == {
            "interview": 0,
            "gd": 0,
            "communication": 1,
            "deck": 0,
        }

    def test_every_metered_feature_has_an_explicit_trial_entry(self):
        """
        A feature ABSENT from the table silently gets 0, which is indistinguishable from a
        deliberate 0 — and the two need opposite fixes. Interviews are 0 because that is the
        pricing; a feature that is 0 because somebody forgot to add it reads to a new user as
        "this is broken". So the assertion is on presence, not on the value.
        """
        for feature in FEATURES:
            assert feature in TRIAL_ALLOWANCE, f"{feature} is missing from TRIAL_ALLOWANCE"
            assert trial_allowance(feature) >= 0

    def test_an_unknown_feature_gets_nothing(self):
        # Metering something this module has never heard of must not become a free
        # allowance by omission.
        assert trial_allowance("video_avatar") == 0


class TestTheCatalogue:
    def test_every_feature_can_be_bought(self):
        # A feature you can run out of but cannot buy is a dead end.
        for feature in FEATURES:
            assert items_for(feature), f"nothing sells {feature}"

    def test_every_item_grants_a_real_feature(self):
        for item in ITEMS:
            assert item.feature in FEATURES, f"{item.id} grants unknown '{item.feature}'"

    def test_prices_and_quantities_are_positive_integers(self):
        # Paise, not rupees, and integers throughout — a price as a float is a rounding bug
        # waiting for the first ₹49.50.
        for item in ITEMS:
            assert isinstance(item.price_paise, int) and item.price_paise > 0
            assert isinstance(item.quantity, int) and item.quantity > 0

    def test_bundles_are_cheaper_per_unit_than_singles(self):
        # Otherwise the bundle is a worse deal presented as a better one, which is the kind
        # of thing a customer works out and does not forgive.
        for feature in FEATURES:
            tiers = items_for(feature)
            singles = [i for i in tiers if i.quantity == 1]
            bundles = [i for i in tiers if i.quantity > 1]
            for b in bundles:
                for s in singles:
                    assert b.unit_price_paise < s.unit_price_paise, (
                        f"{b.id} costs more per unit than {s.id}"
                    )

    def test_the_interview_is_the_most_expensive_single(self):
        # It costs the most to serve and is the only item ending in a full report.
        singles = {i.feature: i for i in ITEMS if i.quantity == 1}
        assert singles["interview"].price_paise > singles["gd"].price_paise
        assert singles["gd"].price_paise > singles["communication"].price_paise

    def test_an_unknown_item_resolves_to_nothing_rather_than_a_default(self):
        # Deliberately unlike the plan lookup this replaced. An unrecognised PLAN could
        # safely degrade to the free tier; an unrecognised ITEM is somebody buying something
        # that does not exist, and quietly selling them the cheapest thing instead is worse
        # than refusing.
        assert get_item("interview_500") is None
        assert get_item("") is None
        assert get_item(None) is None

    def test_item_ids_are_unique(self):
        ids = [i.id for i in ITEMS]
        assert len(ids) == len(set(ids))


def _signed(body: dict, secret: str) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    return raw, hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


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
        # The branch an attacker aims for.
        raw, _ = _signed({"event": "payment.captured"}, "shh")
        assert not verify_signature(raw, "", "shh")

    def test_an_unset_webhook_secret_rejects_everything(self):
        # The correct closed default for a public URL. Empty must not mean "off".
        raw, sig = _signed({"event": "payment.captured"}, "")
        assert not verify_signature(raw, sig, "")

    def test_re_serialised_json_does_not_verify(self):
        # Documents WHY the endpoint hashes raw bytes. Key order and whitespace differ after
        # a parse/dump round trip, so hashing the re-serialised body would reject every
        # genuine webhook — a failure that looks like an attack rather than like a bug.
        raw, sig = _signed({"event": "payment.captured", "b": 1, "a": 2}, "shh")
        reserialised = json.dumps(json.loads(raw), sort_keys=True).encode()
        assert reserialised != raw
        assert not verify_signature(reserialised, sig, "shh")


def _payment(**over) -> dict:
    item = get_item("interview_5")
    assert item is not None
    entity = {
        "id": "pay_ABC123",
        "order_id": "order_XYZ",
        "status": "captured",
        "amount": item.price_paise,
        "notes": {"item_id": item.id, "user_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7"},
    }
    entity.update(over)
    return {"event": "payment.captured", "payload": {"payment": {"entity": entity}}}


class TestReadingAPayment:
    def test_a_captured_payment_grants_the_item(self):
        out = items_from_payment(_payment())
        assert out is not None
        assert out.item.id == "interview_5"
        assert out.item.quantity == 5
        assert out.payment_id == "pay_ABC123"
        assert out.order_id == "order_XYZ"

    def test_an_underpayment_grants_nothing(self):
        # `notes.item_id` is client-influenced. Without checking the amount, ₹1 annotated
        # item_id=interview_5 buys five interviews — the oldest bug in online payments.
        assert items_from_payment(_payment(amount=100)) is None

    def test_an_overpayment_still_grants(self):
        # Refusing money that was actually taken would be worse than accepting it.
        item = get_item("interview_5")
        assert item is not None
        out = items_from_payment(_payment(amount=item.price_paise * 2))
        assert out is not None and out.item.id == "interview_5"

    def test_an_uncaptured_payment_grants_nothing(self):
        assert items_from_payment(_payment(status="authorized")) is None
        assert items_from_payment(_payment(status="failed")) is None

    def test_a_payment_naming_an_unknown_item_grants_nothing(self):
        # Never guess the nearest thing — that would be inventing a purchase nobody made.
        assert items_from_payment(
            _payment(notes={"item_id": "interview_9999", "user_id": "u"})
        ) is None

    def test_a_payment_with_no_user_grants_nothing(self):
        assert items_from_payment(_payment(notes={"item_id": "interview_5"})) is None

    def test_an_unrelated_event_is_ignored_rather_than_erroring(self):
        # Razorpay sends many event types to one URL; the endpoint answers 200 to those so
        # it is not retried forever.
        assert items_from_payment({"event": "refund.created", "payload": {}}) is None
        assert items_from_payment({}) is None
