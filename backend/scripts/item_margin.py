"""
Real per-item margin, AI cost AND speech cost — scripts/item_margin.py

    cd backend && uv run python scripts/item_margin.py
    cd backend && uv run python scripts/item_margin.py --days 90 --json

WHY THIS EXISTS. `services/billing/plans.py` documents its prices against AI cost alone —
"interview ~$0.154, price ₹49, ~73% gross margin". That table is true and it is not the
margin, because speech is a second variable cost that is metered per character, billed by a
different vendor, and counted in a completely different place: `services/tts/spend.py`, a
per-UTC-day Redis counter with a 48-hour TTL and no per-user, per-session or per-feature
attribution at all. Nothing in this repository has ever put the two side by side, so the
only margin figure anybody has been able to quote is the one that leaves out the cost that
can be TWELVE TIMES the AI cost on the wrong vendor (see services/tts/base.py).

THIS IS A REPORT AND IT CHANGES NO PRICE. Deliberately: a price is a product decision, and
this script's job is to put an honest number in front of the person making it.

## The three sources, and how they are joined

    ai_usage           per-call AI cost, labelled with the `context=` string from the
                       generate_structured call site. Joined to a BILLABLE feature by
                       `_AI_FEATURE_TO_BILLABLE` below.
    credit_events      one `kind='consume'` row per item actually delivered. This is the
                       DENOMINATOR — the real count of interviews/GDs/drills sold and run
                       in the window, straight from the ledger the paywall enforces.
    plans.ITEMS        what each of those was charged for.

    AI cost per item  =  SUM(ai_usage.cost_usd for that feature's calls)
                      /  COUNT(credit_events consume rows for that feature)

Both sides are restricted to the same window and both EXCLUDE OPERATOR ACCOUNTS. That
exclusion is load-bearing rather than tidy: `credits.consume` returns before charging for an
admin, so an admin's sessions write NO consume row — but their calls still land in
`ai_usage`. Counting them would divide real admin spend by a denominator that never
included them, and every margin below would read worse than it is. The excluded amount is
reported rather than silently dropped.

## Speech, which cannot be joined and is therefore modelled

`tts_spend_today()` is one float for one day for everybody. There is no row that says which
session, which feature or which user a character was spoken for, so no join to a catalogue
item is possible from the data that exists. Pretending otherwise — dividing today's global
TTS total by today's item count — would produce a number that moves with whatever mix of
features happened to run today, which is worse than useless on a margin sheet.

So speech is MODELLED, from constants that are themselves in the code, and the model is
then RECONCILED against the one real observation available (today's actual counter). Every
input is labelled:

    [CODE]      read from this repository — a setting, a constant, a docstring's own figure
    [LEDGER]    computed from the live ai_usage / credit_events tables in the window
    [MEASURED]  from docs/AI-COST-MODEL.md, produced from logged usage
    [ASSUMED]   a judgement not recorded anywhere in the code

The [ASSUMED] rows are where this can be wrong, so each one is a named constant with the
reasoning attached, and `--json` emits them so a caller can re-run the arithmetic.

## Both vendor scenarios

Asked for, and worth being precise about what "scenario" can mean here: `TTS_PROVIDER` is
process-level configuration read once by `services/tts/factory.py` and cached in a module
global. It is NOT selectable per session, per user or per request, and no request field
reaches it — which is itself a finding this script should state rather than imply. So the
two scenarios are two deployments, not two sessions, and both are priced from the vendors'
own constants (`fish._USD_PER_CHAR`, `elevenlabs._CREDITS_PER_CHAR` x
`_USD_PER_CREDIT_BY_TIER`) rather than from numbers retyped here, so a vendor price edit
cannot leave this report quoting a stale one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field

# ─── Joining the AI ledger to the things people actually buy ─────────────────
#
# `ai_usage.feature` is the `context=` label from the call site — "report_generation",
# "gd_panel_turn". `credit_events.feature` is a BILLABLE feature — "interview", "gd",
# "communication". They are different vocabularies on purpose (see models/ai_usage.py: the
# label IS the call site, so the ledger cannot drift from the code), and this is the only
# place that maps one to the other.
#
# EVERY LABEL IN api/v1/ai_usage.FEATURE_LABELS APPEARS EXACTLY ONCE BELOW, INCLUDING THE
# UNBILLABLE ONES, and a test pins that. A label missing here would silently vanish from the
# report — its spend counted in no item and in no overhead line — which is the one failure
# mode a cost report must not have.
_AI_FEATURE_TO_BILLABLE: dict[str, str | None] = {
    # ── interview ────────────────────────────────────────────────────────
    "interview_plan": "interview",
    "question_generation": "interview",
    "cross_question": "interview",
    "report_generation": "interview",
    "report_analysis": "interview",
    "model_answer": "interview",
    "interview_panel_turn": "interview",
    "panel_code_review": "interview",
    # Fires at plan time for a stream the hand-authored catalogue does not name, and the
    # result is cached per FIELD rather than per candidate — so this is billed to the
    # interview that paid for it, but the second candidate to type the same field pays
    # nothing. It amortises rather than scaling, which is the opposite of every other line
    # above and is worth remembering when this appears smaller than expected.
    "open_domain_profile": "interview",
    # ── group discussion ─────────────────────────────────────────────────
    "gd_panel_turn": "gd",
    "gd_topic_prep": "gd",
    "gd_evaluation": "gd",
    # ── communication drill ──────────────────────────────────────────────
    "communication_evaluation": "communication",
    "communication_cross_question": "communication",
    # ── None: real spend that no purchase pays for ───────────────────────
    #
    # NOT "unimportant" and not roundable to zero. These are the features a free account
    # can use without ever buying anything — resume parsing on signup, quizzes, the shared
    # question pool, the practice-page code evaluator — so their cost is customer
    # acquisition, and it belongs in a per-item margin only if you first decide how many
    # items an acquired customer buys. That is a product decision, so this script reports
    # the total and the per-signup figure and stops there rather than smearing it across
    # the catalogue at a ratio it made up.
    "resume_analysis_skills": None,
    "resume_analysis_projects": None,
    "quiz_generation": None,
    "question_bank": None,
    "code_analysis": None,
    # ── LEGACY LABELS: no call site writes these any more, and the ROWS ARE STILL THERE ──
    #
    # Found by running this script: four labels in the live ledger that no `context=` in the
    # codebase produces. The ledger is append-only and a rename does not rewrite history, so
    # a window that reaches back far enough will always contain spend under the old name —
    # and without these entries that spend lands in the "unmapped" warning and in no cost
    # line, which understates every margin it belongs to.
    #
    # They are kept here rather than backfilled with an UPDATE. `ai_usage` is a record of
    # what was actually billed under what label; rewriting it to match today's naming would
    # destroy the only evidence of when the rename happened.
    #
    #: Pre-split resume parsing. One call returned skills AND projects AND experience before
    #: it became `resume_analysis_skills` + `resume_analysis_projects`. Unbillable then and
    #: unbillable now — resume parsing is free.
    "resume_analysis": None,
    #: Pre-rename `interview_panel_turn`. Still the name of the PROMPT TEMPLATE
    #: (api/v1/panel.py passes system_template="interview_panel"), which is why the two look
    #: alike; the ledger context is the longer one.
    "interview_panel": "interview",
    #: The report's study resources, back when the model generated them. They now come from
    #: the human-verified library (services/prep/study_resources.py) at zero AI cost — see
    #: docs/AI-COST-MODEL.md, "-0.0036 per report". It was part of a report, so it was part
    #: of an interview.
    "study_resources": "interview",
    #: An operational probe, not a product feature: nobody bought it and no item recovers it.
    #: Real money all the same, so it appears in the unbillable total rather than nowhere.
    "latency_probe": None,
}

# ─── What a delivered item costs when the ledger is empty ────────────────────
#
# [MEASURED] docs/AI-COST-MODEL.md and the table in plans.py, both produced from logged
# usage rather than from a rate card. Used ONLY when the window contains no consume rows for
# a feature — a fresh deployment, a test database, a quiet week — and every line of output
# says which source it came from. A report that prints $0.00 margin because nobody bought
# anything last month is a report that gets ignored.
_MEASURED_AI_COST_PER_ITEM: dict[str, float] = {
    # 12 questions + 4 cross-questions + report, with the plan cache hit, after the
    # report rubric became cacheable: $0.1544. plans.py rounds this to ~$0.154.
    "interview": 0.1544,
    # 26 panel turns at $0.0045 + evaluation, with prompt caching on: $0.1423.
    "gd": 0.1423,
    # plans.py: "~$0.02 (₹1.7)". No per-call breakdown is published for this one.
    "communication": 0.02,
}

# ─── Speech: how much of it each item actually is ────────────────────────────


@dataclass(frozen=True)
class SpeechProfile:
    """
    How many characters one item of a feature sends to the vendor.

    Split into two buckets because they behave completely differently under the audio
    cache, and collapsing them is how a GD round and an interview end up looking like the
    same speech bill when one of them is roughly ten times the other in steady state.
    """

    #: Utterances whose TEXT IS THE SAME FOR EVERY CANDIDATE — questions read from the
    #: fixed bank. `_cache_key` in api/v1/tts.py digests provider|voice|tone|speed|text, so
    #: identical text is one cache entry shared by everyone, and TTS_CACHE_TTL_SECONDS is
    #: 14 days precisely because of this. The FIRST candidate pays; nobody else does.
    shared_chars: int
    #: Utterances generated for this candidate — a panel turn, a cross-question, a GD
    #: contribution. Unique text, so the cache can never hit and every one is billed.
    unique_chars: int
    note: str

    @property
    def cold_chars(self) -> int:
        """First-ever candidate on a question set: everything is a cache miss."""
        return self.shared_chars + self.unique_chars

    @property
    def steady_chars(self) -> int:
        """
        Steady state: the shared half is warm, the unique half never is.

        This is the honest per-item marginal figure once the product has any users at all,
        and it is the one the margin table below uses.
        """
        return self.unique_chars


#: [CODE] where the source is named; [ASSUMED] for characters per utterance.
#:
#: CHARACTERS PER UTTERANCE IS THE ONE NUMBER NOT IN THE CODEBASE, and it is the whole
#: model's sensitivity. services/tts/base.py works its own cost table from "~200 characters
#: a contribution" and then totals "~7,800 characters a round" over 26 turns, which is 300,
#: not 200 — the docstring is internally inconsistent. This takes the TOTAL as authoritative
#: over the per-turn figure, because the total is what the dollar table in that file was
#: actually built from, and 300 characters is about two spoken sentences, which is what a
#: panel contribution is.
_CHARS_PER_UTTERANCE = 300

SPEECH: dict[str, SpeechProfile] = {
    "interview": SpeechProfile(
        # [CODE] config.py TTS_RATE_LIMIT_PER_HOUR: "an interview ~16" utterances, of which
        # [CODE] config.py TTS_CACHE_TTL_SECONDS: "the interview reads questions from a
        # FIXED bank — the same ~37 for every candidate — so after the first user those are
        # free". 12 questions [CODE, config INTERVIEW_QUESTION_COUNT] are that bank; the
        # remaining ~4 are panel turns and cross-questions, which are per-candidate.
        shared_chars=12 * _CHARS_PER_UTTERANCE,
        unique_chars=4 * _CHARS_PER_UTTERANCE,
        note="12 bank questions (shared, cached) + ~4 panel/cross utterances (unique)",
    ),
    "gd": SpeechProfile(
        # [CODE] services/tts/base.py: 26 panel turns, ~7,800 characters a round. NONE of it
        # is cacheable — [CODE] config.py TTS_CACHE_TTL_SECONDS again: "the GD one, where
        # every contribution is unique text and will never hit".
        shared_chars=0,
        unique_chars=26 * _CHARS_PER_UTTERANCE,
        note="26 panel turns, every one unique text — the audio cache never hits here",
    ),
    "communication": SpeechProfile(
        # [CODE] api/v1/communication.py: one prompt read from the bank, then one generated
        # cross-question. The evaluation is written, not spoken.
        shared_chars=_CHARS_PER_UTTERANCE,
        unique_chars=_CHARS_PER_UTTERANCE,
        note="1 bank prompt (shared, cached) + 1 generated cross-question (unique)",
    ),
}

# ─── Money that is neither AI nor speech ─────────────────────────────────────

#: [ASSUMED] Razorpay's standard domestic rate is 2% of the transaction, and GST at 18% is
#: charged on the FEE rather than on the transaction — so 2% x 1.18 = 2.36%. plans.py's own
#: docstring says "payment fees (~2-3% + GST)" and stops there; this is the middle of that
#: range worked through. Negotiated rates exist and are lower; override with --payment-fee.
_PAYMENT_FEE_RATE = 0.0236

#: [ASSUMED, derived from CODE] plans.py states the interview's AI cost as "~$0.154 (₹13)",
#: which is 84.4 INR per USD. Taken from the repo's own pairing rather than from a live rate
#: so this report and that table cannot disagree with each other about what ₹49 is worth.
_INR_PER_USD = 84.4


@dataclass
class VendorScenario:
    """One TTS vendor, priced from that vendor's own module."""

    name: str
    usd_per_char: float
    detail: str


def vendor_scenarios() -> list[VendorScenario]:
    """
    Every vendor this deployment could be configured with, at its real per-character price.

    Imported from the provider modules rather than retyped, so `_USD_PER_CHAR` moving in
    fish.py moves this report with it. ElevenLabs is priced at the CONFIGURED model and
    tier — the same two settings `factory.py` passes into the live provider — because the
    tier alone varies the per-character price nearly twofold and quoting the wrong one is
    how a margin sheet is confidently wrong.
    """
    from app.core.config import settings
    from app.services.tts.elevenlabs import _CREDITS_PER_CHAR, _USD_PER_CREDIT_BY_TIER
    from app.services.tts.fish import _USD_PER_CHAR as FISH_USD_PER_CHAR

    tier = (settings.ELEVENLABS_TIER or "creator").lower()
    model = settings.ELEVENLABS_MODEL or "eleven_flash_v2_5"
    # Same fallbacks the provider itself uses: an unknown tier bills at Creator (the
    # priciest per credit), an unknown model at 1.0 credits per character. Both err toward
    # over-stating cost, which is the right direction for a spend figure to be wrong in.
    per_credit = _USD_PER_CREDIT_BY_TIER.get(tier, _USD_PER_CREDIT_BY_TIER["creator"])
    per_char = _CREDITS_PER_CHAR.get(model, 1.0) * per_credit

    return [
        VendorScenario(
            name="fish",
            usd_per_char=FISH_USD_PER_CHAR,
            detail=f"~${FISH_USD_PER_CHAR * 1_000_000:.2f}/M chars (model {settings.FISH_MODEL})",
        ),
        VendorScenario(
            name="elevenlabs",
            usd_per_char=per_char,
            detail=f"{model} on tier '{tier}' — ${per_char * 1_000_000:.2f}/M chars",
        ),
    ]


# ─── The arithmetic, kept pure so it is testable without a database ──────────


@dataclass
class FeatureCost:
    """What one delivered item of a feature costs us, before payment fees."""

    feature: str
    #: Where `ai_cost_usd` came from: "ledger" or "measured-fallback".
    ai_source: str
    ai_cost_usd: float
    #: Items delivered in the window, from credit_events. 0 when falling back.
    items: int
    #: Total attributed AI spend in the window, before dividing.
    ai_total_usd: float
    #: Speech cost per item, per vendor name, in steady state (shared audio cached).
    tts_cost_usd: dict[str, float] = field(default_factory=dict)
    #: Speech cost per item for the very first candidate, when nothing is cached yet.
    tts_cold_usd: dict[str, float] = field(default_factory=dict)


def feature_costs(
    ai_total_by_feature: dict[str, float],
    items_by_feature: dict[str, int],
    scenarios: list[VendorScenario],
) -> dict[str, FeatureCost]:
    """
    Cost per delivered item, per billable feature.

    `ai_total_by_feature` and `items_by_feature` are both already restricted to the window
    and already exclude operator accounts; this function does no filtering and no database
    access, which is what makes it testable and what keeps the filtering in one place.
    """
    out: dict[str, FeatureCost] = {}
    for feature, profile in SPEECH.items():
        items = items_by_feature.get(feature, 0)
        total = ai_total_by_feature.get(feature, 0.0)
        if items > 0:
            ai_cost, source = total / items, "ledger"
        else:
            # No purchases consumed in this window. Falling back rather than reporting a
            # margin of 100% on a divide-by-zero guard, which is the failure that makes a
            # cost report look fine and be nonsense.
            ai_cost, source = _MEASURED_AI_COST_PER_ITEM[feature], "measured-fallback"
        out[feature] = FeatureCost(
            feature=feature,
            ai_source=source,
            ai_cost_usd=ai_cost,
            items=items,
            ai_total_usd=total,
            tts_cost_usd={
                s.name: profile.steady_chars * s.usd_per_char for s in scenarios
            },
            tts_cold_usd={s.name: profile.cold_chars * s.usd_per_char for s in scenarios},
        )
    return out


@dataclass
class ItemMargin:
    """One catalogue item, priced against what it costs to deliver."""

    item_id: str
    name: str
    feature: str
    quantity: int
    price_inr: float
    price_usd: float
    #: Razorpay's cut, on the whole purchase.
    payment_fee_usd: float
    #: AI cost for the whole bundle — per-item cost x quantity.
    ai_cost_usd: float
    #: Per vendor: speech cost for the whole bundle.
    tts_cost_usd: dict[str, float]
    #: Per vendor: price - payment fee - AI - speech.
    margin_usd: dict[str, float]
    margin_pct: dict[str, float]
    #: The figure plans.py currently quotes: no speech, no payment fee.
    ai_only_margin_pct: float


def item_margins(
    costs: dict[str, FeatureCost],
    scenarios: list[VendorScenario],
    *,
    payment_fee_rate: float = _PAYMENT_FEE_RATE,
    inr_per_usd: float = _INR_PER_USD,
) -> list[ItemMargin]:
    """Every item in the catalogue, at every vendor scenario. Pure."""
    from app.services.billing.plans import ITEMS

    rows: list[ItemMargin] = []
    for item in ITEMS:
        cost = costs[item.feature]
        price_inr = item.price_paise / 100
        price_usd = price_inr / inr_per_usd
        fee = price_usd * payment_fee_rate
        ai = cost.ai_cost_usd * item.quantity

        tts = {s.name: cost.tts_cost_usd[s.name] * item.quantity for s in scenarios}
        margin = {name: price_usd - fee - ai - t for name, t in tts.items()}
        rows.append(
            ItemMargin(
                item_id=item.id,
                name=item.name,
                feature=item.feature,
                quantity=item.quantity,
                price_inr=price_inr,
                price_usd=price_usd,
                payment_fee_usd=fee,
                ai_cost_usd=ai,
                tts_cost_usd=tts,
                margin_usd=margin,
                margin_pct={
                    name: (m / price_usd * 100) if price_usd else 0.0
                    for name, m in margin.items()
                },
                ai_only_margin_pct=(
                    (price_usd - ai) / price_usd * 100 if price_usd else 0.0
                ),
            )
        )
    return rows


# ─── Reading the two ledgers ─────────────────────────────────────────────────


async def _read_ledgers(days: int) -> tuple[dict[str, float], dict[str, int], dict]:
    """
    (AI spend per billable feature, items delivered per feature, diagnostics).

    Both queries exclude operator accounts by an OUTER JOIN to `users` and a test on
    `is_admin`, rather than by a subquery `NOT IN`, so a NULL `user_id` — a background job,
    or a row whose account was erased — is KEPT rather than silently dropped. Erased
    accounts still spent real money and `ai_usage.user_id` is SET NULL on delete precisely
    so that fact survives; a `NOT IN` against a NULL would have thrown it away.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, or_, select

    from app.db.session import AsyncSessionFactory
    from app.models.ai_usage import AIUsage
    from app.models.billing import CreditEvent
    from app.models.user import User
    from app.services.billing.credits import KIND_CONSUME

    since = datetime.now(UTC) - timedelta(days=days)
    not_admin = or_(User.id.is_(None), User.is_admin.is_(False))

    ai_by_billable: dict[str, float] = {}
    unbillable_total = 0.0
    unmapped: dict[str, float] = {}
    admin_total = 0.0

    async with AsyncSessionFactory() as db:
        rows = (
            await db.execute(
                select(AIUsage.feature, func.coalesce(func.sum(AIUsage.cost_usd), 0))
                .outerjoin(User, User.id == AIUsage.user_id)
                .where(AIUsage.created_at >= since, not_admin)
                .group_by(AIUsage.feature)
            )
        ).all()
        for feature, total in rows:
            usd = float(total or 0)
            if feature not in _AI_FEATURE_TO_BILLABLE:
                # An unmapped label is a real call site this script does not know about, so
                # it is reported loudly instead of being dropped into a bucket.
                unmapped[feature] = usd
                continue
            billable = _AI_FEATURE_TO_BILLABLE[feature]
            if billable is None:
                unbillable_total += usd
            else:
                ai_by_billable[billable] = ai_by_billable.get(billable, 0.0) + usd

        admin_total = float(
            await db.scalar(
                select(func.coalesce(func.sum(AIUsage.cost_usd), 0))
                .join(User, User.id == AIUsage.user_id)
                .where(AIUsage.created_at >= since, User.is_admin.is_(True))
            )
            or 0
        )

        item_rows = (
            await db.execute(
                select(CreditEvent.feature, func.count())
                .outerjoin(User, User.id == CreditEvent.user_id)
                .where(
                    CreditEvent.created_at >= since,
                    CreditEvent.kind == KIND_CONSUME,
                    not_admin,
                )
                .group_by(CreditEvent.feature)
            )
        ).all()
        items = {feature: int(count) for feature, count in item_rows}

        signups = int(
            await db.scalar(
                select(func.count()).select_from(User).where(User.created_at >= since)
            )
            or 0
        )

    return (
        ai_by_billable,
        items,
        {
            "unbillable_ai_usd": unbillable_total,
            "unmapped_ai_features": unmapped,
            "admin_ai_usd_excluded": admin_total,
            "signups": signups,
            "since": since.isoformat(),
        },
    )


async def _observed_tts_today() -> float | None:
    """
    Today's real speech spend, for reconciliation. None when Redis is unreachable.

    The ONLY real observation of TTS cost that exists anywhere, and it is a single global
    float for a single UTC day — which is exactly why the per-item figures above had to be
    modelled. Printed beside the model so the two can be compared by whoever is looking at
    a real day's traffic.
    """
    try:
        from app.services.tts.spend import tts_spend_today

        return await tts_spend_today()
    except Exception:  # noqa: BLE001 — a diagnostic must not take down the report
        return None


# ─── Output ──────────────────────────────────────────────────────────────────


def _render(
    costs: dict[str, FeatureCost],
    rows: list[ItemMargin],
    scenarios: list[VendorScenario],
    diagnostics: dict,
    observed_tts: float | None,
    days: int,
    payment_fee_rate: float,
    inr_per_usd: float,
) -> str:
    out: list[str] = []
    w = out.append

    w("=" * 96)
    w(f"PER-ITEM MARGIN, AI + SPEECH — last {days} days, since {diagnostics['since'][:10]}")
    w("=" * 96)
    w("")
    w("This is a report. No price in plans.py is changed by running it.")
    w("")

    w("─ Vendor scenarios (TTS_PROVIDER is process-level config, not per session) ─")
    for s in scenarios:
        w(f"  {s.name:<12} {s.detail}")
    w("")

    w("─ Cost per delivered item ─────────────────────────────────────────────────")
    header = f"  {'feature':<14} {'items':>6} {'AI $/item':>11} {'source':>18}"
    for s in scenarios:
        header += f" {'tts:' + s.name:>14}"
    w(header)
    for feature, c in costs.items():
        line = (
            f"  {feature:<14} {c.items:>6} {c.ai_cost_usd:>11.4f} {c.ai_source:>18}"
        )
        for s in scenarios:
            line += f" {c.tts_cost_usd[s.name]:>14.4f}"
        w(line)
    w("")
    w("  Speech figures are STEADY STATE — shared bank audio is cached after the first")
    w("  candidate (TTS_CACHE_TTL_SECONDS = 14 days). Cold, first-candidate cost:")
    for feature, c in costs.items():
        cold = ", ".join(f"{s.name} ${c.tts_cold_usd[s.name]:.4f}" for s in scenarios)
        w(f"    {feature:<14} {cold}    ({SPEECH[feature].note})")
    w("")

    w("─ Margin per catalogue item ───────────────────────────────────────────────")
    w(f"  Payment fee {payment_fee_rate * 100:.2f}%   FX ₹{inr_per_usd}/USD")
    w("")
    head = f"  {'item':<18} {'₹':>6} {'$':>7} {'fee':>7} {'AI':>8}"
    for s in scenarios:
        head += f" {s.name[:9] + ' tts':>13} {s.name[:9] + ' mgn':>13}"
    head += f" {'AI-only mgn':>12}"
    w(head)
    for r in rows:
        line = (
            f"  {r.item_id:<18} {r.price_inr:>6.0f} {r.price_usd:>7.3f} "
            f"{r.payment_fee_usd:>7.3f} {r.ai_cost_usd:>8.4f}"
        )
        for s in scenarios:
            line += (
                f" {r.tts_cost_usd[s.name]:>13.4f}"
                f" {r.margin_pct[s.name]:>12.1f}%"
            )
        line += f" {r.ai_only_margin_pct:>11.1f}%"
        w(line)
    w("")
    w("  'AI-only mgn' is the figure plans.py currently documents: no speech, no payment")
    w("  fee. The gap between it and the vendor columns is what this script was written")
    w("  to make visible.")
    w("")

    w("─ Costs no item pays for ──────────────────────────────────────────────────")
    unbillable = diagnostics["unbillable_ai_usd"]
    signups = diagnostics["signups"]
    w("  Unbillable AI spend in window (resume, quiz, question bank, practice code):")
    w(f"    ${unbillable:.4f} across {signups} new accounts", )
    if signups:
        w(f"    = ${unbillable / signups:.4f} per new account, recovered from no item")
    w(f"  Operator-account AI spend excluded from the per-item figures above: "
      f"${diagnostics['admin_ai_usd_excluded']:.4f}")
    if diagnostics["unmapped_ai_features"]:
        w("")
        w("  !! UNMAPPED ai_usage.feature LABELS — their spend is in NO line above:")
        for feature, usd in sorted(
            diagnostics["unmapped_ai_features"].items(), key=lambda kv: -kv[1]
        ):
            w(f"     {feature:<32} ${usd:.4f}")
        w("     Add each to _AI_FEATURE_TO_BILLABLE in this file.")
    w("")

    w("─ Reconciliation against the one real speech observation ──────────────────")
    if observed_tts is None:
        w("  tts_spend_today() unavailable (no Redis). The modelled figures above stand")
        w("  on the vendor constants alone.")
    else:
        w(f"  tts_spend_today() = ${observed_tts:.4f}")
        w("  One global float, today only, 48h TTL, no per-feature or per-user attribution")
        w("  — see services/tts/spend.py. It cannot be divided into the items above, which")
        w("  is why they are modelled. Compare it against (items delivered today x the")
        w("  per-item speech figure for the configured vendor) to sanity-check the model.")
    w("")
    w("=" * 96)
    return "\n".join(out)


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1].strip())
    parser.add_argument("--days", type=int, default=30, help="Window size in days.")
    parser.add_argument(
        "--payment-fee",
        type=float,
        default=_PAYMENT_FEE_RATE,
        help=f"Payment gateway rate as a fraction. Default {_PAYMENT_FEE_RATE}.",
    )
    parser.add_argument(
        "--inr-per-usd",
        type=float,
        default=_INR_PER_USD,
        help=f"FX rate. Default {_INR_PER_USD}, from plans.py's own $/₹ pairing.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    args = parser.parse_args(argv)

    scenarios = vendor_scenarios()
    try:
        ai_totals, items, diagnostics = await _read_ledgers(args.days)
    except Exception as exc:  # noqa: BLE001
        # A margin report that refuses to run without a database is a margin report nobody
        # runs. The measured fallbacks are labelled as such in every row, so an operator
        # cannot mistake this output for live figures.
        print(
            f"warning: could not read the ledgers ({type(exc).__name__}: {exc}).\n"
            "         Falling back to the MEASURED figures in docs/AI-COST-MODEL.md.\n",
            file=sys.stderr,
        )
        from datetime import UTC, datetime, timedelta

        ai_totals, items = {}, {}
        diagnostics = {
            "unbillable_ai_usd": 0.0,
            "unmapped_ai_features": {},
            "admin_ai_usd_excluded": 0.0,
            "signups": 0,
            "since": (datetime.now(UTC) - timedelta(days=args.days)).isoformat(),
            "ledger_error": f"{type(exc).__name__}: {exc}",
        }

    costs = feature_costs(ai_totals, items, scenarios)
    rows = item_margins(
        costs,
        scenarios,
        payment_fee_rate=args.payment_fee,
        inr_per_usd=args.inr_per_usd,
    )
    observed = await _observed_tts_today()

    if args.json:
        print(
            json.dumps(
                {
                    "window_days": args.days,
                    "assumptions": {
                        "chars_per_utterance": _CHARS_PER_UTTERANCE,
                        "payment_fee_rate": args.payment_fee,
                        "inr_per_usd": args.inr_per_usd,
                    },
                    "vendors": [asdict(s) for s in scenarios],
                    "per_item_cost": {k: asdict(v) for k, v in costs.items()},
                    "items": [asdict(r) for r in rows],
                    "diagnostics": diagnostics,
                    "observed_tts_spend_today_usd": observed,
                },
                indent=2,
                default=float,
            )
        )
    else:
        print(
            _render(
                costs,
                rows,
                scenarios,
                diagnostics,
                observed,
                args.days,
                args.payment_fee,
                args.inr_per_usd,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
