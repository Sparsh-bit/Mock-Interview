"""
The RBI e-mandate position of auto top-up — tests/test_autopay_mandate_compliance.py

WHAT WAS ASKED: does autopay use Razorpay's own subscription/e-mandate rails — which would
make Razorpay, as the licensed payment aggregator, the party responsible for Additional
Factor Authentication — or a custom saved-token flow, which would need independent compliance
work this product does not have?

WHAT TRACING THE CODE FOUND. Both halves of the answer matter and the second is the
surprise.

  1. It is Razorpay's own recurring rails. `charge_saved_token` posts to
     `https://api.razorpay.com/v1/payments/create/recurring` with `customer_id`, `token` and
     `recurring: "1"` — Razorpay's "create subsequent payment" API. There is no custom token
     vault, no card data anywhere in this system, and `autopay_token` is an opaque Razorpay
     reference. AFA at mandate registration therefore happens inside Razorpay's own
     authorisation transaction, which is where the RBI framework puts it.

  2. THE REGISTRATION FLOW DOES NOT EXIST. `autopay_token` and `autopay_customer_id` are
     read in three places and written in NONE. Nothing creates a Razorpay customer, nothing
     runs an authorisation transaction, and no webhook captures a `token_id`. So
     `is_eligible` returns "no saved mandate" for every account that will ever exist, and
     no charge can be made. There is also no frontend for any of it.

So the compliant/needs-work call is: **compliant today because nothing can be charged, and
needs the registration flow built before it could ever be enabled** — and that flow is
precisely where AFA lives.

WHY THESE ARE TESTS AND NOT ONLY A NOTE. The dangerous way to "finish" this feature is to
populate `autopay_token` from somewhere other than a Razorpay authorisation transaction — a
value pasted from the dashboard, a token borrowed from a manual payment — because that
produces a working charge that skipped AFA entirely. These fail if the token gains a write
path without the authorisation flow arriving with it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_APP = pathlib.Path(__file__).resolve().parents[1] / "app"
_AUTOPAY = _APP / "services" / "billing" / "autopay.py"

#: RBI, Digital Payments — E-Mandate Framework, 2026
#: (RBI/CO.DPSS.POLC.No.S56/02.14.003/2026-27, 21 April 2026): subsequent recurring
#: transactions up to this may be processed without AFA. Higher ceilings apply to insurance,
#: mutual funds and card bills, none of which this is.
AFA_EXEMPT_CEILING_PAISE = 15_000 * 100


class TestItIsRazorpaysOwnRailsAndNotACustomTokenVault:
    def test_the_charge_goes_to_razorpays_recurring_endpoint(self):
        source = _AUTOPAY.read_text(encoding="utf-8")
        assert "https://api.razorpay.com/v1/payments/create/recurring" in source

    def test_it_sends_the_recurring_flag_and_razorpays_own_identifiers(self):
        """
        `recurring: "1"` with a `customer_id` and a `token` is Razorpay's subsequent-payment
        shape. It is what makes this THEIR mandate rather than our stored instrument.
        """
        source = _AUTOPAY.read_text(encoding="utf-8")
        for field in ('"recurring": "1"', '"customer_id"', '"token"'):
            assert field in source, f"the recurring charge does not send {field}"

    def test_no_card_data_is_handled_anywhere_in_billing(self):
        """
        THE FACT THAT KEEPS THIS SIMPLE. A merchant that never sees a card cannot be the
        party storing one, which is what puts PCI-DSS and the storage half of the RBI
        localisation question out of scope by design.
        """
        forbidden = ("card_number", "card_no", '"cvv"', "cvv=", "expiry_month", "pan_number")
        offenders: list[str] = []
        for path in (_APP / "services" / "billing").rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for needle in forbidden:
                if needle in text:
                    offenders.append(f"{path.name}: {needle}")
        assert not offenders, f"card data appears in the billing layer: {offenders}"

    def test_it_is_not_the_subscriptions_api(self):
        """
        Recorded because the two are easy to confuse and the compliance answer differs.
        Razorpay Subscriptions is `POST /v1/subscriptions` against a `plan_id`; this product
        deliberately has no subscriptions (see plans.py) and uses saved-token charges.
        """
        source = _AUTOPAY.read_text(encoding="utf-8")
        assert "/v1/subscriptions" not in source
        assert "plan_id" not in source


class TestNothingCanActuallyBeCharged:
    """
    The inertness is the current compliance position, so it is pinned rather than assumed.
    """

    def test_no_code_path_writes_the_mandate_token(self):
        """
        THE LOAD-BEARING ONE. A write to `autopay_token` that does not come from a Razorpay
        authorisation transaction is a charge that skipped AFA. Parsed with `ast` rather
        than grepped so an assignment cannot hide behind formatting.
        """
        writes: list[str] = []
        for path in sorted(_APP.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                targets: list[ast.expr] = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                    targets = [node.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr in ("autopay_token", "autopay_customer_id")
                        # The model's own column declaration is not a write.
                        and path.name != "billing.py"
                    ):
                        writes.append(f"{path.relative_to(_APP.parent)}:{node.lineno}")

        assert not writes, (
            "something now writes the autopay mandate token: "
            f"{writes}\n\n"
            "This is not necessarily wrong — but it is only correct if the value came from "
            "a Razorpay AUTHORISATION TRANSACTION, which is where RBI's Additional Factor "
            "Authentication happens (E-Mandate Framework 2026, AFA mandatory at "
            "registration for all channels and all amounts). A token obtained any other "
            "way — pasted from the dashboard, reused from a one-off payment — produces a "
            "working charge that skipped AFA.\n\n"
            "If the registration flow has been built, update docs/DATA-RESIDENCY.md and "
            "this test together."
        )

    def test_an_account_without_a_mandate_is_never_eligible(self):
        from app.models.billing import UserPlan
        from app.services.billing.autopay import is_eligible

        plan = UserPlan(autopay_enabled=True, autopay_item_id="interview_5", autopay_token=None)
        eligible, reason = is_eligible(plan)

        assert eligible is False
        assert "mandate" in reason

    def test_enabling_autopay_does_not_by_itself_authorise_anything(self):
        """
        `POST /billing/autopay` records intent. It must never be the thing that makes a
        charge possible — that is what the mandate is for.
        """
        source = (_APP / "api" / "v1" / "billing.py").read_text(encoding="utf-8")
        start = source.index('@router.post("/autopay"')
        end = source.index("@router.get", start)
        handler = source[start:end]

        assert "autopay_token" not in handler.replace("bool(plan.autopay_token)", ""), (
            "the enable endpoint touches the mandate token"
        )

    def test_the_feature_has_no_user_interface(self):
        """
        Part of why the current position is safe: there is no way for a candidate to reach
        this at all. If a UI appears, the registration flow has to appear with it.
        """
        frontend = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
        hits = [
            p.name
            for p in frontend.rglob("*.ts*")
            # TEST FILES EXCLUDED. A frontend test that names autopay — to assert it is
            # absent, or in a comment pointing here — is not an autopay interface, and
            # counting it makes this guard fire on somebody documenting the guard.
            if not p.name.endswith((".test.ts", ".test.tsx"))
            and "autopay" in p.read_text(encoding="utf-8", errors="ignore").lower()
        ]
        assert not hits, (
            f"an autopay UI now exists ({hits}) — confirm the mandate registration flow, "
            "and its AFA step, were built alongside it"
        )


class TestTheAmountsStayInsideTheAfaExemption:
    @pytest.mark.parametrize(
        "item_id", ["interview_1", "gd_1", "communication_1", "interview_5", "gd_5", "communication_10"]
    )
    def test_every_purchasable_item_is_below_the_afa_exempt_ceiling(self, item_id):
        """
        Subsequent recurring transactions above ₹15,000 need AFA on every debit, which no
        unattended top-up can supply. Every pack here is two orders of magnitude below that,
        and this fails if a price is ever set that would change the regulatory shape of the
        feature rather than just its cost.
        """
        from app.services.billing.plans import get_item

        item = get_item(item_id)
        assert item is not None
        assert item.price_paise < AFA_EXEMPT_CEILING_PAISE, (
            f"{item_id} at ₹{item.price_paise / 100:,.2f} is above the ₹15,000 AFA "
            "exemption, so an unattended recurring charge of it would need per-debit "
            "authentication"
        )
