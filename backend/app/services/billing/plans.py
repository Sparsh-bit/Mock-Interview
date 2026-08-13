"""
The trial, and what each thing costs to buy — services/billing/plans.py

THE SINGLE SOURCE OF TRUTH FOR ENTITLEMENT AND PRICE. The enforcement layer, the paywall
copy, the pricing page and the landing page all read these numbers. There is deliberately no
second list anywhere: a page that advertises ₹49 while the server charges ₹79 is a refund and
a support ticket, and that divergence is invisible until a paying customer hits it.

## No subscription. A trial, then you buy what you use.

This replaced a monthly Starter/Pro model, and the change is not cosmetic — it is a
different business.

A subscription asks somebody to bet ₹299 on using the product enough to justify it. The
users here are campus students with a placement season a few weeks long: they want three
interviews the week before a drive and nothing for the two months after. For that shape,
a monthly plan is a bad deal in both directions — they overpay in quiet months and feel
metered in busy ones — and the decision to subscribe is a much bigger commitment than the
decision to buy one more interview tonight.

So: **one free trial of each feature, then a fixed price per item, with no expiry.** The
question at the paywall stops being "is this worth ₹299 a month" and becomes "is one more
mock interview worth ₹49", which is a far easier yes and is asked at the exact moment the
answer is obviously yes — they have just finished one and want another.

`TRIAL` is not a plan anybody stays on. It is the one-time allowance every account starts
with, and once spent, entitlement comes entirely from purchased items.

## Why the prices are what they are

Measured costs, not estimates — see docs/AI-COST-MODEL.md, produced from the logged usage
ledger rather than from vendor rate cards:

| item | our AI cost | price | gross margin |
|---|---:|---:|---:|
| interview (12 questions + report) | ~$0.154 (₹13) | **₹49** | ~73% |
| group discussion (26 turns + scoring) | ~$0.142 (₹12) | **₹39** | ~69% |
| communication drill | ~$0.02 (₹1.7) | **₹19** | ~91% |

Margins look generous against raw AI cost and are not, once payment fees (~2-3% + GST),
speech, hosting and the free trials of everyone who never buys are taken out. The trial
alone is roughly ₹27 of AI given away per signup.

**The interview is priced highest because it costs the most and is worth the most** — it is
the only item that ends in a full report. The communication drill is priced well above its
cost deliberately: at ₹5 it would be an impulse buy nobody values, and a drill is worth
more to a candidate than a fifth of an interview.

Bundles exist because a single ₹49 purchase has the same payment-gateway overhead as a
₹199 one, and because somebody buying five interviews has decided to prepare properly
rather than to try one more thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: The metered features. Anything not listed here is free and unlimited.
#:
#: `quiz` is deliberately absent rather than present with a large number — quizzes cost
#: nothing to serve from the curated bank, they are the habit that brings somebody back on a
#: day they have no time for an interview, and an unlimited feature behaves differently at
#: the boundary from one with a high cap.
Feature = Literal["interview", "gd", "communication"]

FEATURES: tuple[Feature, ...] = ("interview", "gd", "communication")

# Keyed by `str` rather than by `Feature`, deliberately. A feature name reaching this at
# runtime has come from a database column or a request body, so it is a plain string however
# tightly the call site is typed — and a lookup needing a cast at every use is a lookup that
# will eventually be done without one.
FEATURE_LABELS: dict[str, str] = {
    "interview": "mock interviews",
    "gd": "group discussions",
    "communication": "communication drills",
}

#: Singular, for "buy 1 more ___" copy. Kept beside the plural so a new feature cannot ship
#: with a raw identifier leaking into a purchase button.
FEATURE_LABELS_SINGULAR: dict[str, str] = {
    "interview": "mock interview",
    "gd": "group discussion",
    "communication": "communication drill",
}

#: THE TRIAL. One of everything, once, for the lifetime of the account.
#:
#: One interview rather than two: the trial's job is to prove the product works, and one
#: interview ending in a full hire/no-hire report does that. A second is what somebody buys
#: once they have seen the first — which is the whole model.
#:
#: NOT per month. There is no renewal anywhere in this file; see `credits.py` for why the
#: absence of a period is what makes the ledger simpler rather than harder.
TRIAL_ALLOWANCE: dict[str, int] = {
    "interview": 1,
    "gd": 1,
    "communication": 1,
}


@dataclass(frozen=True)
class Item:
    """One purchasable thing, or a bundle of them."""

    id: str
    #: Which feature this grants. Bundles grant several of ONE feature; a mixed bundle would
    #: need the ledger to record a quantity per feature and is not worth that today.
    feature: str
    quantity: int
    #: Price in paise, the unit Razorpay bills in. Integers throughout — a price in rupees as
    #: a float is a rounding bug waiting for the first ₹49.50.
    price_paise: int
    name: str
    tagline: str

    @property
    def price_rupees(self) -> int:
        return self.price_paise // 100

    @property
    def unit_price_paise(self) -> int:
        return self.price_paise // self.quantity


#: The catalogue. Ordered as the store renders it: single items first, then bundles.
ITEMS: tuple[Item, ...] = (
    Item(
        id="interview_1",
        feature="interview",
        quantity=1,
        price_paise=4_900,
        name="1 mock interview",
        tagline="Twelve questions, the two-person panel, and a full report.",
    ),
    Item(
        id="gd_1",
        feature="gd",
        quantity=1,
        price_paise=3_900,
        name="1 group discussion",
        tagline="Eight minutes against three AI panelists, then scored.",
    ),
    Item(
        id="communication_1",
        feature="communication",
        quantity=1,
        price_paise=1_900,
        name="1 communication drill",
        tagline="Speak an answer, get scored on delivery.",
    ),
    Item(
        id="interview_5",
        feature="interview",
        quantity=5,
        price_paise=19_900,
        name="5 mock interviews",
        tagline="For a placement season rather than a single drive.",
    ),
    Item(
        id="gd_5",
        feature="gd",
        quantity=5,
        price_paise=15_900,
        name="5 group discussions",
        tagline="Enough rounds to stop freezing in the first two minutes.",
    ),
    Item(
        id="communication_10",
        feature="communication",
        quantity=10,
        price_paise=14_900,
        name="10 communication drills",
        tagline="Daily practice for a fortnight.",
    ),
)

_BY_ID: dict[str, Item] = {i.id: i for i in ITEMS}


def get_item(item_id: str | None) -> Item | None:
    """
    An item by id, or None.

    Returns None rather than falling back to anything. This is unlike `get_plan` in the
    subscription model it replaced, and the asymmetry is deliberate: an unrecognised PLAN
    could safely degrade to the free tier, whereas an unrecognised ITEM is somebody trying
    to buy something that does not exist, and quietly selling them the cheapest thing on the
    list instead would be worse than refusing.
    """
    return _BY_ID.get((item_id or "").strip().lower())


def items_for(feature: str) -> tuple[Item, ...]:
    """Everything that grants `feature`, cheapest first — the upgrade sheet's contents."""
    return tuple(
        sorted((i for i in ITEMS if i.feature == feature), key=lambda i: i.price_paise)
    )


def trial_allowance(feature: str) -> int:
    """
    How many of `feature` the one-time trial includes.

    An unknown feature returns 0. Metering something this module has never heard of must not
    quietly become a free allowance.
    """
    return TRIAL_ALLOWANCE.get(feature, 0)
