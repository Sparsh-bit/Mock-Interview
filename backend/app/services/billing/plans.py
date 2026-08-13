"""
What each plan includes, and what it costs — services/billing/plans.py

THE SINGLE SOURCE OF TRUTH FOR ENTITLEMENT. The enforcement layer, the paywall copy, the
pricing page and the landing page all read these numbers. There is deliberately no second
list anywhere: a pricing page that advertises ten interviews while the server allows eight is
a support ticket and a refund, and that divergence is invisible until a paying customer hits
it.

WHY PER-FEATURE QUOTAS RATHER THAN ONE POOL OF CREDITS. A single "credits" number is simpler
to implement and worse to use — it forces the candidate to do arithmetic about whether a GD
round is worth three interviews before they start one, at exactly the moment they should be
thinking about the interview. Named allowances ("2 interviews, 1 group discussion") are what
the product promises out loud, so they are what it should count.

## The costs these are priced against

Measured, not estimated — see docs/AI-COST-MODEL.md, which was produced from the logged usage
ledger rather than from vendor rate cards:

  * one full interview (12 questions + 4 cross-questions + report)  ~$0.17 cold, $0.23 warm
  * one full GD round (26 panel turns + evaluation)                 ~$0.14
  * speech, on the current Fish free tier                            ~$0

The report alone is 58% of an interview and is output-bound, so it does not get cheaper with
caching. That is the number that sets the floor under all of this.

## Why the free tier is shaped the way it is

Two interviews, one GD, five communications is roughly **$0.60** of AI per signup. That is
deliberately a real cost rather than a token one: a free tier that cannot show the product
working does not convert, and the expensive part — the report — is precisely the part worth
seeing. Two interviews is enough to get a report, act on it, and see the second one improve,
which is the whole argument for the product.

Quizzes are unlimited and always free because they cost nothing to serve from the curated
bank, and they are the habit that brings somebody back on the days they do not have forty
minutes for a full interview.

## Why the paid tiers are priced where they are

Priced in INR because the users are Indian campus students, and against what that audience
actually pays for exam prep rather than against USD SaaS norms.

  Starter ₹299  →  ~$3.60.  8 x $0.20 + 4 x $0.14 = $2.16 of AI.  ~40% gross margin.
  Pro     ₹699  →  ~$8.40.  20 x $0.20 + 12 x $0.14 = $5.68 of AI.  ~32% gross margin.

Those margins are thin on purpose and are the reason the allowances are not rounder, more
generous numbers. Thirty interviews at ₹499 — which reads like a much better offer — is $6.00
of cost against $6.00 of revenue, so every heavy user on that plan would be served at a loss
and growth would make the problem worse rather than better. If the report's output cost falls,
raise the allowances; do not lower the prices first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: The metered features. Anything not listed here is free and unlimited.
#:
#: `quiz` is deliberately absent rather than present with a large number — an unlimited
#: feature and a feature with a high cap behave differently at the boundary, and quizzes
#: should never have a boundary.
Feature = Literal["interview", "gd", "communication"]

FEATURES: tuple[Feature, ...] = ("interview", "gd", "communication")

#: Human-readable, for paywall copy and the report of what ran out. Kept beside the features
#: themselves so a new feature cannot ship with a raw identifier leaking into the UI.
# Keyed by `str` rather than by `Feature`, deliberately. A feature name reaching this at
# runtime has come from a database column or a request body, so it is a plain string however
# tightly the call site is typed — and a lookup that needs a cast at every use is a lookup
# that will eventually be done without one.
FEATURE_LABELS: dict[str, str] = {
    "interview": "mock interviews",
    "gd": "group discussions",
    "communication": "communication drills",
}

#: Sentinel for "no limit". A large integer rather than None so every comparison downstream
#: stays a plain `used < allowance` — a nullable allowance means every call site needs a
#: None branch, and the one that forgets is the one that charges a paying customer.
UNLIMITED = 1_000_000


@dataclass(frozen=True)
class Plan:
    """One purchasable tier."""

    id: str
    name: str
    #: Monthly price in paise, the unit Razorpay bills in. Integers throughout — a price in
    #: rupees as a float is a rounding bug waiting for the first ₹299.99.
    price_paise: int
    tagline: str
    allowances: dict[str, int]
    #: Shown on the pricing page under the numbers.
    highlights: tuple[str, ...]

    @property
    def price_rupees(self) -> int:
        return self.price_paise // 100

    @property
    def is_free(self) -> bool:
        return self.price_paise == 0


FREE = Plan(
    id="free",
    name="Free",
    price_paise=0,
    tagline="Enough to see whether this actually helps you.",
    allowances={"interview": 2, "gd": 1, "communication": 5},
    highlights=(
        "Unlimited quizzes, forever",
        "Full hire/no-hire report on every interview",
        "The two-person AI panel, with voice",
        "No card required",
    ),
)

STARTER = Plan(
    id="starter",
    name="Starter",
    price_paise=29_900,
    tagline="For the few weeks before your placement season.",
    allowances={"interview": 8, "gd": 4, "communication": 25},
    highlights=(
        "Everything in Free",
        "8 full interviews a month",
        "Coding and SQL rounds, graded",
        "Progress tracking across rounds",
    ),
)

PRO = Plan(
    id="pro",
    name="Pro",
    price_paise=69_900,
    tagline="For clearing a specific company, not just practising.",
    allowances={"interview": 20, "gd": 12, "communication": UNLIMITED},
    highlights=(
        "Everything in Starter",
        "20 full interviews a month",
        "Unlimited communication drills",
        "Company-specific preparation",
    ),
)

#: Ordered cheapest first — the pricing page and the upgrade prompt both render in this order,
#: and "the next plan up" is defined by this sequence rather than by comparing prices.
PLANS: tuple[Plan, ...] = (FREE, STARTER, PRO)

_BY_ID: dict[str, Plan] = {p.id: p for p in PLANS}

#: The plan a user has when nothing says otherwise. Named rather than inlined because
#: "unknown plan falls back to free" must be one decision made in one place — falling back to
#: a PAID plan on a lookup miss would give away the product, and falling back to nothing would
#: lock out every user whose plan row has not been created yet.
DEFAULT_PLAN_ID = FREE.id


def get_plan(plan_id: str | None) -> Plan:
    """
    A plan by id, falling back to Free.

    Total by design. A plan id read from the database can be stale — a tier that was renamed
    or withdrawn — and the safe response to "I do not recognise this plan" is to serve the
    free allowance, not to raise inside a request that is trying to start an interview.
    """
    return _BY_ID.get((plan_id or "").strip().lower(), FREE)


def allowance_for(plan_id: str | None, feature: str) -> int:
    """
    How many of `feature` this plan includes per period.

    An unknown FEATURE returns 0 rather than UNLIMITED. That asymmetry with `get_plan` is
    deliberate: an unrecognised plan is a data problem and should degrade to the free tier,
    whereas an unrecognised feature means somebody is metering something this module has never
    heard of, and quietly granting it unlimited use is how a metered feature ships free.
    """
    return get_plan(plan_id).allowances.get(feature, 0)
