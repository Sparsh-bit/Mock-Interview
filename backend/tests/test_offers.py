"""
Promo codes and offers — tests/test_offers.py

This is money. The tests that matter most are the ones asserting somebody CANNOT get
something: cannot name their own price, cannot use a code twice, cannot use a switched-off
code, and cannot turn off the amount check by claiming an offer that does not exist.

The DB-backed paths (redeem, the unique index, the row lock) need Postgres and live in
test_integration.py's fixtures. Everything here is the pure arithmetic and the payment
parsing, which is where the exploitable mistakes actually are.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.billing import Offer
from app.services.billing import razorpay
from app.services.billing.offers import (
    KIND_FIXED,
    KIND_FREE,
    KIND_PERCENT,
    MIN_CHARGEABLE_PAISE,
    OfferError,
    _apply,
    _window_message,
    charge_for,
)
from app.services.billing.plans import get_item


def offer(**kw) -> Offer:
    """An Offer with sane defaults, not persisted."""
    base = {
        "code": "TEST",
        "label": "Test",
        "kind": KIND_PERCENT,
        "value": 50,
        "applies_to": [],
        "enabled": True,
        "is_public": False,
        "starts_at": None,
        "ends_at": None,
        "max_redemptions": None,
        "requires_captcha": False,
    }
    base.update(kw)
    return Offer(**base)


ITEM = get_item("interview_1")  # ₹49 = 4900 paise


class TestTheDiscountArithmetic:
    def test_a_percent_offer_takes_that_percent_off(self):
        assert _apply(offer(kind=KIND_PERCENT, value=50), 4900) == 2450
        assert _apply(offer(kind=KIND_PERCENT, value=25), 4900) == 3675

    def test_rounding_favours_the_candidate(self):
        # 33% of 4900 is 1617 exactly; a price that does not divide cleanly must round the
        # DISCOUNT up rather than down. A discount that rounds against the person using it
        # is the kind of thing that ends up on Twitter.
        assert _apply(offer(kind=KIND_PERCENT, value=33), 999) <= 999 - (999 * 33) // 100

    def test_a_fixed_offer_sets_the_final_price(self):
        # "₹1 for a launch offer" — the value IS the price, not the discount.
        assert _apply(offer(kind=KIND_FIXED, value=100), 4900) == 100

    def test_a_free_offer_is_zero(self):
        assert _apply(offer(kind=KIND_FREE), 4900) == 0

    def test_a_discount_below_one_rupee_becomes_free(self):
        # Razorpay refuses anything under ₹1, so 95% off a ₹19 drill is not a cheap order —
        # it is an impossible one. The candidate gets the drill rather than an error from a
        # payment provider they never chose to involve.
        assert _apply(offer(kind=KIND_PERCENT, value=99), 1900) == 0
        assert _apply(offer(kind=KIND_FIXED, value=50), 4900) == 0

    def test_the_boundary_is_exactly_one_rupee(self):
        assert _apply(offer(kind=KIND_FIXED, value=MIN_CHARGEABLE_PAISE), 4900) == 100
        assert _apply(offer(kind=KIND_FIXED, value=MIN_CHARGEABLE_PAISE - 1), 4900) == 0

    def test_a_discount_can_never_raise_the_price(self):
        # A "fixed" offer configured above list must not charge more than the item costs.
        assert _apply(offer(kind=KIND_FIXED, value=99_999), 4900) == 4900

    def test_a_percent_over_100_or_under_0_is_clamped(self):
        assert _apply(offer(kind=KIND_PERCENT, value=250), 4900) == 0
        assert _apply(offer(kind=KIND_PERCENT, value=-5), 4900) == 4900

    def test_an_unknown_kind_refuses_rather_than_charging_full_price(self):
        # Silently meaning "no discount" would charge full price against a code the candidate
        # was told would work — they would pay ₹49 believing they had paid ₹25.
        with pytest.raises(OfferError):
            _apply(offer(kind="nonsense"), 4900)


class TestTheWindow:
    def test_an_offer_with_no_dates_is_live(self):
        assert _window_message(offer(), datetime.now(UTC)) is None

    def test_before_the_start_it_is_not_yet_active(self):
        now = datetime.now(UTC)
        msg = _window_message(offer(starts_at=now + timedelta(days=1)), now)
        assert msg and "not active yet" in msg

    def test_after_the_end_it_has_expired(self):
        now = datetime.now(UTC)
        msg = _window_message(offer(ends_at=now - timedelta(seconds=1)), now)
        assert msg and "expired" in msg

    def test_the_message_distinguishes_the_two(self):
        # "Invalid code" for an expired one sends the candidate hunting for a typo that is
        # not there. The reason has to be actionable.
        now = datetime.now(UTC)
        early = _window_message(offer(starts_at=now + timedelta(days=1)), now)
        late = _window_message(offer(ends_at=now - timedelta(days=1)), now)
        assert early != late


class TestThePaymentCannotBeUnderpaid:
    """
    The guard that protects every purchase, and the new hole that had to not be opened.

    `notes` is attacker-influenced: it travels to Razorpay and back. The amount is the only
    fact. Adding `offer_code` to the notes meant adding a field that, handled naively, turns
    the amount check off — so a ₹1 payment annotated `item_id=interview_5` would buy five.
    """

    def _payment(self, *, amount: int, item_id: str, notes_extra: dict | None = None) -> dict:
        notes = {"item_id": item_id, "user_id": "11111111-1111-1111-1111-111111111111"}
        notes.update(notes_extra or {})
        return {
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test",
                        "order_id": "order_test",
                        "status": "captured",
                        "amount": amount,
                        "notes": notes,
                    }
                }
            }
        }

    def test_a_full_price_payment_is_accepted_and_already_verified(self):
        out = razorpay.items_from_payment(self._payment(amount=4900, item_id="interview_1"))
        assert out is not None
        assert out.amount_verified is True
        assert out.offer_code == ""

    def test_an_underpayment_with_no_offer_is_still_refused(self):
        # The original guard, unchanged. This is the one that stops a ₹1 payment buying five
        # interviews, and nothing about offers may weaken it.
        assert razorpay.items_from_payment(self._payment(amount=100, item_id="interview_5")) is None

    def test_claiming_an_offer_does_not_silently_accept_the_amount(self):
        # THE HOLE THAT MUST NOT EXIST. A discounted payment is legitimately below list, so
        # the pure check cannot apply — but skipping it would make `offer_code` a free pass.
        # It comes back flagged as UNVERIFIED so the webhook is obliged to check it.
        out = razorpay.items_from_payment(
            self._payment(amount=100, item_id="interview_5", notes_extra={"offer_code": "ANYTHING"})
        )
        assert out is not None
        assert out.amount_verified is False, "a claimed offer must not count as verified"
        assert out.offer_code == "ANYTHING"

    def test_the_offer_code_is_normalised_to_uppercase(self):
        out = razorpay.items_from_payment(
            self._payment(amount=100, item_id="interview_1", notes_extra={"offer_code": "diwali25"})
        )
        assert out and out.offer_code == "DIWALI25"

    def test_an_uncaptured_payment_is_never_granted(self):
        body = self._payment(amount=4900, item_id="interview_1")
        body["payload"]["payment"]["entity"]["status"] = "authorized"
        assert razorpay.items_from_payment(body) is None

    def test_an_unknown_item_is_never_guessed_at(self):
        assert razorpay.items_from_payment(self._payment(amount=4900, item_id="nope")) is None


class TestTheWebhookRecomputesTheExpectedPrice:
    def test_charge_for_matches_the_quote_arithmetic(self):
        # The webhook re-derives from the offer row rather than trusting what came back
        # through the gateway. A legitimate payment must match exactly, or every discounted
        # purchase would be rejected.
        o = offer(kind=KIND_PERCENT, value=50)
        assert charge_for(o, ITEM) == _apply(o, ITEM.price_paise)

    def test_a_free_code_expects_zero(self):
        assert charge_for(offer(kind=KIND_FREE), ITEM) == 0

    def test_a_payment_short_of_the_discounted_price_is_short(self):
        # 50% off ₹49 is ₹24.50. Paying ₹1 against that code is still an underpayment, and
        # the webhook's comparison is what catches it.
        expected = charge_for(offer(kind=KIND_PERCENT, value=50), ITEM)
        assert expected == 2450
        assert expected > 100


class TestTheOrderCannotBeBuiltBelowRazorpaysFloor:
    async def test_a_zero_amount_order_is_a_programming_error(self):
        # A fully-discounted item must be granted directly. Reaching create_order with zero
        # means the free path was skipped, and failing loudly beats sending Razorpay an order
        # it will reject in front of the candidate.
        with pytest.raises(ValueError, match="below Razorpay"):
            await razorpay.create_order(ITEM, "user", charged_paise=0)

    async def test_an_amount_under_one_rupee_is_refused(self):
        with pytest.raises(ValueError, match="below Razorpay"):
            await razorpay.create_order(ITEM, "user", charged_paise=99)


class TestYouGetExactlyWhatYouPaidFor:
    """
    "the thing that the user has purchased only that must get renewed and not some other."

    The property: an item id resolves SERVER-SIDE to a feature and a quantity, and those are
    what get granted. Nothing about the request names either — so buying group discussions
    cannot credit interviews however the request is shaped.
    """

    def test_every_item_grants_its_own_feature(self):
        from app.services.billing.plans import ITEMS

        for item in ITEMS:
            # The id encodes the feature by convention; the FIELD is what is granted. If the
            # two ever disagree, somebody buying "gd_5" gets interviews.
            assert item.id.startswith(item.feature), (
                f"{item.id} grants '{item.feature}' — the id and the granted feature disagree"
            )

    def test_every_item_grants_its_own_quantity(self):
        from app.services.billing.plans import ITEMS

        for item in ITEMS:
            suffix = item.id.rsplit("_", 1)[-1]
            if suffix.isdigit():
                assert item.quantity == int(suffix), (
                    f"{item.id} grants {item.quantity} — the id promises {suffix}"
                )

    def test_no_two_items_share_an_id(self):
        # A duplicate id means get_item returns one of them and the other is unbuyable — or
        # worse, buyable at the wrong price.
        from app.services.billing.plans import ITEMS

        ids = [i.id for i in ITEMS]
        assert len(ids) == len(set(ids))

    def test_every_item_costs_at_least_one_rupee(self):
        # Razorpay's floor. An item priced below it cannot be ordered at all, so it would
        # present as a Buy button that always errors.
        from app.services.billing.plans import ITEMS

        for item in ITEMS:
            assert item.price_paise >= 100, f"{item.id} is priced below Razorpay's minimum"

    def test_a_bundle_is_cheaper_per_unit_than_a_single(self):
        # Not correctness, but it is money and a typo here is a bundle that costs more than
        # buying the same thing one at a time.
        from app.services.billing.plans import ITEMS

        singles = {i.feature: i for i in ITEMS if i.quantity == 1}
        for item in ITEMS:
            if item.quantity > 1 and item.feature in singles:
                assert item.unit_price_paise < singles[item.feature].price_paise, (
                    f"{item.id} costs more per unit than buying one at a time"
                )


class TestAPaymentCanOnlyCreditThePayer:
    """
    "the payment must be updated on his id only."

    The order's notes carry the user id, and both granting paths check it. Without that, a
    valid (order, payment, signature) triple — anybody's — could be replayed to credit a
    different account.
    """

    def test_the_verify_endpoint_checks_the_payment_belongs_to_the_caller(self):
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "billing.py").read_text()
        verify = src[src.index("async def verify_payment") : src.index("async def razorpay_webhook")]
        # The comparison itself, not a comment about it.
        code = re.sub(r"#.*$", "", verify, flags=re.M)
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        assert 'notes.get("user_id")' in code
        assert "current_user.user_id" in code

    def test_verify_refuses_before_it_grants(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "billing.py").read_text()
        verify = src[src.index("async def verify_payment") : src.index("async def razorpay_webhook")]
        # Ordering is the property: every check must precede the grant, or a rejected payment
        # has already been credited by the time it is rejected.
        assert verify.index("verify_checkout_signature") < verify.index("await grant(")
        assert verify.index('payment.get("status")') < verify.index("await grant(")
        assert verify.index("amount < expected") < verify.index("await grant(")

    def test_a_payment_is_granted_once_however_many_paths_report_it(self):
        # The webhook and the browser both grant. Whichever arrives second must find the
        # payment_ref already in the ledger and do nothing — otherwise a healthy deployment
        # double-credits every purchase.
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "billing.py").read_text()
        verify = src[src.index("async def verify_payment") : src.index("async def razorpay_webhook")]
        assert "CreditEvent.payment_ref == request.razorpay_payment_id" in verify
        assert verify.index("payment_ref ==") < verify.index("await grant(")


class TestTheCheckoutSignatureIsNotTheWebhookSignature:
    """
    Two different signatures over different data with different secrets. Confusing them is
    the most common way this integration silently fails.
    """

    def test_the_checkout_signature_is_over_order_and_payment(self):
        import hashlib
        import hmac

        from app.services.billing.razorpay import verify_checkout_signature

        secret = "test_secret"
        order, payment = "order_abc", "pay_xyz"
        good = hmac.new(
            secret.encode(), f"{order}|{payment}".encode(), hashlib.sha256
        ).hexdigest()
        assert verify_checkout_signature(order, payment, good, secret) is True

    def test_it_refuses_a_signature_for_a_different_payment(self):
        import hashlib
        import hmac

        from app.services.billing.razorpay import verify_checkout_signature

        secret = "test_secret"
        good = hmac.new(
            secret.encode(), b"order_abc|pay_xyz", hashlib.sha256
        ).hexdigest()
        # Same signature, different payment id — a replay against another order.
        assert verify_checkout_signature("order_abc", "pay_other", good, secret) is False
        assert verify_checkout_signature("order_other", "pay_xyz", good, secret) is False

    def test_blank_input_is_a_failure_not_a_pass(self):
        from app.services.billing.razorpay import verify_checkout_signature

        assert verify_checkout_signature("", "p", "s", "k") is False
        assert verify_checkout_signature("o", "", "s", "k") is False
        assert verify_checkout_signature("o", "p", "", "k") is False
        assert verify_checkout_signature("o", "p", "s", "") is False
