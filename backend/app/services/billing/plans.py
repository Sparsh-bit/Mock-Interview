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

## `ITEMS` IS THE SHELF, NOT THE WHOLE CATALOGUE

There is one purchasable thing that is deliberately NOT in `ITEMS`: `REPORT_UNLOCK_ITEM`,
the ₹49 unlock for a free interview's report. Read its comment before adding anything else
off-shelf, because the distinction is easy to get wrong in both directions.

`ITEMS` is what `GET /billing/items` renders — the pricing page. Everything on it is a
stock of a metered feature you can buy in advance and spend later. The report unlock is not
that: it belongs to one session's report, it is offered at the paywall on that report and
nowhere else, and a tile advertising it to somebody with no locked report would be an offer
they cannot use.

`_BY_ID` still holds it, so `get_item("report_unlock_1")` resolves. That single line is what
lets the entire existing payment machinery sell it with no changes anywhere:
`/billing/checkout` prices it server-side, `razorpay.create_order` puts its id in the
order notes, `items_from_payment` and `/billing/verify` check the amount against
`price_paise` and grant it, and `offers.quote` can discount it — which is where the coupon
code the owner asked for comes from. Off the shelf, but fully in the machine.
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
    # NOT A METERED FEATURE — see REPORT_UNLOCK_FEATURE below for why it is absent from
    # `Feature`, `FEATURES` and `TRIAL_ALLOWANCE` and present here.
    #
    # It is here because these two dicts are pure COPY, read by anything that has a ledger
    # feature string and needs a sentence: `CreditsExhaustedError` builds its 402 message
    # from them, and the admin marketing view lists ledger rows per account. Both would
    # otherwise print the raw identifier — "You have no report_unlock left" — and the comment
    # on the singular dict below says exactly why that must not happen. A label costs
    # nothing and cannot change an allowance; `get_balance` iterates `FEATURES`, not this,
    # so nothing new appears on anybody's balance meter.
    "report_unlock": "personalised reports",
}

#: Singular, for "buy 1 more ___" copy. Kept beside the plural so a new feature cannot ship
#: with a raw identifier leaking into a purchase button.
FEATURE_LABELS_SINGULAR: dict[str, str] = {
    "interview": "mock interview",
    "gd": "group discussion",
    "communication": "communication drill",
    "report_unlock": "personalised report",
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

# ─── The report unlock ────────────────────────────────────────────────────────
#
# ₹49 to see the personalised report and study material for a FREE interview. The interview
# itself stays free; only its report is paid. A PURCHASED interview's report is included in
# what was bought — charging twice for one session would be indefensible — so the unlock only
# ever applies to a session drawn from the free trial.
#
# The gate lives in services/billing/report_access.py, which decides free-vs-bought off the
# credit ledger and fails open on every path. This file only says what the thing is and what
# it costs, exactly as it does for everything else.

#: The ledger `feature` string for a report unlock.
#:
#: A DISTINCT STRING RATHER THAN A FOURTH `Feature`, AND THIS IS THE LOAD-BEARING CHOICE IN
#: THE WHOLE PAYWALL. `Feature` is a `Literal` of three and `FEATURES` is a tuple of the
#: same three, and both were left alone on purpose:
#:
#:   1. `FEATURES` IS THE BALANCE METER. `credits.get_balance` loops it and builds one
#:      `FeatureBalance` per entry, which `GET /billing/me` returns and the dashboard
#:      renders. A fourth entry would put "0 personalised reports left" on every account in
#:      the product, including everybody who has never left a report locked. That
#:      is a broken-looking meter for a thing that is not a stock: an unlock belongs to ONE
#:      session's report, not to a wallet you draw down.
#:
#:   2. `TRIAL_ALLOWANCE` AND THE FREE TIER MUST BE PROVABLY UNCHANGED. The strongest
#:      available proof that the free interview, GD and communication allowances did not
#:      move is that not one character of `Feature`, `FEATURES` or `TRIAL_ALLOWANCE` was
#:      touched — no new key, no reordering, nothing for a reviewer to have to reason about.
#:      A test asserts all three literally. Widening the Literal would have meant arguing
#:      that a new member changes nothing, which is a weaker thing to have to argue.
#:      `trial_allowance("report_unlock")` therefore returns 0 through the documented
#:      unknown-feature path, which is correct: there is no free personalised report, and a
#:      report that is free once is a report the paywall never charges for.
#:
#:   3. A PLAIN STRING IS ALREADY THE SUPPORTED INPUT. `consume` and `grant` take
#:      `feature: str`, and the comment on FEATURE_LABELS explains why: a feature name
#:      reaching the ledger has come from a database column or a request body, so it is a
#:      plain string however tightly the call site is typed. `CreditEvent.feature` is
#:      `String(32)`. Nothing needed widening for this to be recordable — which is also why
#:      NO MIGRATION IS INVOLVED.
#:
#: What is given up is that mypy cannot spot a typo'd "report_unlok" at a call site. That is
#: bought back by there being exactly one literal — this constant — and every caller
#: importing it.
REPORT_UNLOCK_FEATURE = "report_unlock"

#: ₹49, in paise, because Razorpay bills in paise and every price in this repo is an integer.
#:
#: MATCHING WHAT AN INTERVIEW COSTS, deliberately. `interview_1` is 4_900 and this sits beside
#: it in the candidate's head: the interview they just took for free is worth ₹49, and so is
#: understanding how they did in it. A price of its own invention reads as a made-up number;
#: one that matches the product's own price reads as the product's price. Set by the owner —
#: "i want the same interview price their the 49 rupees not 50".
#:
#: AGAINST COST: an interview and its report together are ~₹13 of AI (see the table above),
#: and on a free interview the interview half is given away. So ₹49 covers the whole session
#: with room for payment fees, and the report is the half a candidate actually wants to keep.
#:
#: Comfortably above the 100-paise Razorpay floor, with room for a coupon to take a large bite
#: without producing an order the gateway refuses.
REPORT_UNLOCK_PRICE_PAISE = 4_900

#: The unlock, as a normal purchasable `Item` — deliberately NOT in `ITEMS`.
#:
#: See the "ITEMS IS THE SHELF" section at the top of this file for why it is off-shelf and
#: how it still reaches every part of the payment machinery. In short: it is an `Item` so
#: that checkout, order creation, amount verification, the webhook, the grant and the coupon
#: engine all handle it with no code of their own; it is out of `ITEMS` so the pricing page
#: does not advertise a report to somebody who has no session to unlock.
#:
#: `quantity=1` and it means one unlock, spendable on one session. Somebody who buys two —
#: two free interviews, two reports — gets two, and the ledger says which session each was
#: spent on.
REPORT_UNLOCK_ITEM = Item(
    id="report_unlock_1",
    feature=REPORT_UNLOCK_FEATURE,
    quantity=1,
    price_paise=REPORT_UNLOCK_PRICE_PAISE,
    name="Unlock your personalised report",
    tagline="Your full scorecard, the per-question breakdown and the study plan.",
)

#: Id lookup. ITEMS plus the off-shelf unlock, so `get_item` resolves everything that can be
#: PAID FOR while `ITEMS` stays everything that is LISTED. Those are two different questions
#: and this is the one line where they differ; conflating them is how an unlisted item
#: becomes unbuyable (checkout 404s on its own id) or a session-scoped item becomes a tile on
#: the pricing page.
_BY_ID: dict[str, Item] = {i.id: i for i in (*ITEMS, REPORT_UNLOCK_ITEM)}


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
