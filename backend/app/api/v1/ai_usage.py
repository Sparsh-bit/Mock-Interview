"""
TEMPORARY — AI cost breakdown. api/v1/ai_usage.py

Scheduled for deletion once credits and subscriptions land; see
`docs/TEMPORARY-token-counter.md` at the repo root.

Answers the questions you need answered before pricing a credit:

  * which feature is spending the money, per call and in total
  * how much of that spend is being thrown away on discarded responses
  * what one user costs — mean, median and p95 — which is the number a credit
    price has to cover
  * how much prompt caching is actually saving

ADMIN ONLY, AND FAIL CLOSED. This is cost data about the business, so an
ordinary account must not see it. Two independent gates:

  * `AdminUser` — the app's existing admin dependency, checked against
    users.is_admin. Returns 403, consistent with every other admin route. A 404
    would hide the endpoint's existence better, but inventing a different
    behaviour for one route is worse than the small disclosure.
  * `AI_USAGE_LEDGER_ENABLED` — returns 404 when off, so switching the ledger
    off by config makes the view vanish rather than serve an empty report that
    looks like "no spend".

The order matters: the admin check runs first, as a dependency, so a non-admin
cannot use the 404-vs-403 difference to learn whether the flag is on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import AdminUser
from app.db.session import get_db
from app.models.ai_usage import AIUsage
from app.services.ai import vector_cache

router = APIRouter(prefix="/ai-usage", tags=["ai-usage (temporary)"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

#: What each feature is, in the product, in one line. Keyed by the `context`
#: label passed at the generate_structured call site — the same string stored in
#: the ledger — so a feature that appears in the data always resolves here, and
#: one that does not is a call site somebody forgot to label.
FEATURE_LABELS: dict[str, str] = {
    "interview_plan": "Interview plan (pre-generates the whole question set)",
    "question_generation": "Adaptive question during an interview",
    "question_bank": "Shared question pool — generated once per role, then cached for everyone",
    "cross_question": "Live follow-up probing the last answer",
    "report_generation": "Final report — summary, scores, roadmap",
    # The per-question breakdown, generated in concurrent batches alongside the summary
    # above. Listed separately because it is several calls per report, so a rise here
    # means longer interviews rather than more reports — and those need different
    # answers. See services/report/composer.py.
    "report_analysis": "Final report — per-question breakdown",
    "model_answer": "Detailed analysis: the answer they should have given",
    # TWO CALLS, NOT ONE, and the ledger names them separately because they are separately
    # billed and separately capable of failing. Resume parsing was one call that had to return
    # skills AND projects AND experience in a single structured response; splitting it in two
    # means a model that fumbles the projects half no longer costs the candidate their skills,
    # and the two halves run concurrently so the upload is faster. See services/resume/
    # analyser.py and the two prompts/resume_analyzer_*.md templates.
    "resume_analysis_skills": "Resume parsing — skills and experience",
    "resume_analysis_projects": "Resume parsing — projects",
    "quiz_generation": "Practice quiz questions",
    "code_analysis": "Coding round evaluation",
    "communication_evaluation": "Communication round scoring",
    "communication_cross_question": "Communication round follow-up",
    "interview_panel_turn": "Interview panel — what the two interviewers say around a question",
    # Distinct from `code_analysis`, which is the same evaluator reached from /code/analyse
    # for the practice page. Kept apart on purpose: this one fires inside a live interview,
    # once per coding submission, so it scales with interviews rather than with practice runs
    # and needs to be visible separately when the credit costing is set.
    "panel_code_review": "Interview panel — grading the code before the panel reviews it",
    "gd_panel_turn": "Group discussion — one AI panellist's turn",
    "gd_topic_prep": "Group discussion — turning a candidate's own topic into a motion",
    "gd_evaluation": "Group discussion scoring",
    # Fires only for a stream the hand-authored catalogue does not name, and the entry is
    # shared across every candidate who types that field — so this line should stay small
    # even as interviews grow. If it does not, the catalogue is missing a family that a lot
    # of people are asking for, and that is the signal to author one rather than to keep
    # paying for it. See services/interview/open_domain.py.
    "open_domain_profile": "Interview brief for a field the catalogue does not cover",
}


def _money(v: Decimal | float | int | None) -> float:
    """Decimal → float at the API boundary. Sums happen in NUMERIC, in the DB."""
    return round(float(v or 0), 6)


def _provider_chain_status() -> dict:
    """
    Which AI providers are actually live in this process, and whether a fallback exists.

    Reads the CONSTRUCTED chain rather than the settings, because the two can disagree in the
    way that matters: a fallback is configured, its key is missing, construction fails, and the
    chain silently runs one provider long. Settings would say "fallback: glm" and be wrong.

    Never raises. This is a diagnostic on an admin page, and a diagnostic that can 500 the page
    it is meant to explain is worse than no diagnostic.
    """
    try:
        from app.services.ai.provider_factory import get_ai_providers  # noqa: PLC0415

        chain = [p.provider_name for p in get_ai_providers()]
    except Exception as exc:  # noqa: BLE001
        return {"chain": [], "has_fallback": False, "error": type(exc).__name__}
    return {
        "chain": chain,
        "configured_primary": settings.AI_PROVIDER,
        "configured_fallback": settings.AI_FALLBACK_PROVIDER or "",
        # THE FIELD TO LOOK AT. False means one provider deep: healthy today, and a total
        # outage the moment that provider refuses.
        "has_fallback": len(chain) > 1,
    }


@router.get("", summary="Per-feature AI token use and cost (temporary, admin only)")
async def get_ai_usage(
    current_user: AdminUser,
    days: int = Query(30, ge=1, le=365, description="Window size in days."),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    if not settings.AI_USAGE_LEDGER_ENABLED:
        raise _NOT_FOUND

    since = datetime.now(UTC) - timedelta(days=days)
    window = AIUsage.created_at >= since

    # Reused across every rollup below. Summing cost in the database keeps it in
    # NUMERIC the whole way; pulling rows into Python and adding floats is how a
    # cost report ends up disagreeing with the provider's invoice.
    money = func.coalesce(func.sum(AIUsage.cost_usd), 0)
    calls = func.count()
    tok_in = func.coalesce(func.sum(AIUsage.input_tokens), 0)
    tok_cached = func.coalesce(func.sum(AIUsage.cached_input_tokens), 0)
    tok_write = func.coalesce(func.sum(AIUsage.cache_write_tokens), 0)
    tok_out = func.coalesce(func.sum(AIUsage.output_tokens), 0)
    discarded_cost = func.coalesce(
        func.sum(
            AIUsage.cost_usd
            * cast(AIUsage.outcome == "discarded", Integer)
        ),
        0,
    )
    discarded_calls = func.coalesce(
        func.sum(cast(AIUsage.outcome == "discarded", Integer)), 0
    )

    # ── Totals ───────────────────────────────────────────────────────────────
    t = (
        await db.execute(
            select(calls, tok_in, tok_cached, tok_write, tok_out, money,
                   discarded_cost, discarded_calls).where(window)
        )
    ).one()
    total_cost = _money(t[5])

    totals = {
        "calls": t[0] or 0,
        "input_tokens": t[1] or 0,
        "cached_input_tokens": t[2] or 0,
        "cache_write_tokens": t[3] or 0,
        "output_tokens": t[4] or 0,
        "cost_usd": total_cost,
        "discarded_cost_usd": _money(t[6]),
        "discarded_calls": t[7] or 0,
    }

    # ── By feature — the main view ───────────────────────────────────────────
    rows = (
        await db.execute(
            select(
                AIUsage.feature, calls, tok_in, tok_cached, tok_write, tok_out,
                money, discarded_cost, discarded_calls,
            )
            .where(window)
            .group_by(AIUsage.feature)
            .order_by(money.desc())
        )
    ).all()

    by_feature = [
        {
            "feature": r[0],
            "label": FEATURE_LABELS.get(r[0], r[0].replace("_", " ").capitalize()),
            "calls": r[1],
            "input_tokens": r[2] or 0,
            "cached_input_tokens": r[3] or 0,
            "cache_write_tokens": r[4] or 0,
            "output_tokens": r[5] or 0,
            "cost_usd": _money(r[6]),
            # The figure that actually decides what to optimise: a feature can be
            # cheap per call and still dominate the bill by being called often,
            # or cost 40x per call and barely register.
            "avg_cost_per_call_usd": _money(Decimal(str(r[6])) / r[1]) if r[1] else 0.0,
            "discarded_cost_usd": _money(r[7]),
            "discarded_calls": r[8] or 0,
            "share_pct": round(_money(r[6]) / total_cost * 100, 1) if total_cost else 0.0,
        }
        for r in rows
    ]

    # ── By model ────────────────────────────────────────────────────────────
    model_rows = (
        await db.execute(
            select(AIUsage.provider, AIUsage.model, calls, money)
            .where(window)
            .group_by(AIUsage.provider, AIUsage.model)
            .order_by(money.desc())
        )
    ).all()
    by_model = [
        {"provider": r[0], "model": r[1], "calls": r[2], "cost_usd": _money(r[3])}
        for r in model_rows
    ]

    # ── By day, so a spike has a date on it ─────────────────────────────────
    day = func.date_trunc("day", AIUsage.created_at)
    day_rows = (
        await db.execute(
            select(day, calls, money).where(window).group_by(day).order_by(day)
        )
    ).all()
    by_day = [
        {"day": r[0].date().isoformat(), "calls": r[1], "cost_usd": _money(r[2])}
        for r in day_rows
    ]

    # ── Cost per user — what a credit has to cover ───────────────────────────
    #
    # Mean alone is misleading: interview usage is long-tailed, a handful of
    # users run many sessions, and pricing to the mean underprices exactly those
    # accounts. The median says what a typical user costs; p95 says what the
    # expensive tail costs, which is the number a flat monthly price must
    # survive. percentile_cont interpolates, which is what you want on money.
    per_user_totals = (
        select(AIUsage.user_id, func.sum(AIUsage.cost_usd).label("c"))
        .where(window, AIUsage.user_id.isnot(None))
        .group_by(AIUsage.user_id)
        .subquery()
    )
    pu = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.avg(per_user_totals.c.c), 0),
                func.coalesce(
                    func.percentile_cont(0.5).within_group(per_user_totals.c.c), 0
                ),
                func.coalesce(
                    func.percentile_cont(0.95).within_group(per_user_totals.c.c), 0
                ),
                func.coalesce(func.max(per_user_totals.c.c), 0),
            ).select_from(per_user_totals)
        )
    ).one()

    unattributed = (
        await db.execute(
            select(money).where(window, AIUsage.user_id.is_(None))
        )
    ).scalar()

    # PRICING THE CACHE, which the stats alone cannot do.
    #
    # vector_cache.stats() counts hits; the ledger knows what a call of that feature costs.
    # Neither is the saving on its own, and the two have been sitting side by side in this
    # response without ever being multiplied — so "the cache is working" has been an
    # assertion rather than a figure.
    #
    # Priced from the average cost per call IN THIS WINDOW, not from a constant: model
    # prices change, prompt caching moved the GD turn by 59%, and a saving quoted against
    # last quarter's rate is a made-up number.
    #
    # Hits are LIFETIME per entry while the spend window is `days`, so on a short window
    # this over-states. Stated rather than silently corrected, because the alternative —
    # recording a timestamp on every cache read — is a write on the hot path to make a
    # reporting figure tidier.
    cache_rows = await vector_cache.stats(db)
    cost_per_call = {r["feature"]: r["avg_cost_per_call_usd"] for r in by_feature}
    avoided_by_feature: list[dict] = []
    avoided_total = 0.0
    for row in cache_rows:
        unit = float(cost_per_call.get(row["feature"], 0.0))
        avoided = row["hits"] * unit
        avoided_total += avoided
        avoided_by_feature.append(
            {
                "feature": row["feature"],
                "hits": row["hits"],
                "entries": row["entries"],
                "never_hit": row["never_hit"],
                "cost_per_call_usd": unit,
                "avoided_usd": round(avoided, 6),
                # Hits per entry is the saturation signal, and it is the one to watch. A
                # shared cache only makes the product cheaper at scale if entries are reused
                # many times over: climbing across releases means the key space is bounded
                # and the cache is saturating; flat near 1.0 means it never will.
                "hits_per_entry": (
                    round(row["hits"] / row["entries"], 2) if row["entries"] else 0.0
                ),
            }
        )
    avoided_by_feature.sort(key=lambda r: r["avoided_usd"], reverse=True)

    return {
        "temporary": True,
        "note": (
            "Estimated from provider-reported token counts and the price sheet in "
            "anthropic_provider._PRICE_PER_MTOK. Treat as a close upper bound, not "
            "an invoice. This view is removed when credits ship."
        ),
        "window_days": days,
        "since": since.isoformat(),
        "totals": totals,
        "by_feature": by_feature,
        "by_model": by_model,
        "by_day": by_day,
        "per_user": {
            "users_with_spend": pu[0] or 0,
            "mean_cost_usd": _money(pu[1]),
            "median_cost_usd": _money(pu[2]),
            "p95_cost_usd": _money(pu[3]),
            "max_cost_usd": _money(pu[4]),
            # Background jobs and anything run outside a request have no user.
            "unattributed_cost_usd": _money(unattributed),
        },
        "daily_budget_usd": settings.AI_DAILY_BUDGET_USD,
        "user_daily_budget_usd": settings.AI_USER_DAILY_BUDGET_USD,
        # ── THE LIVE PROVIDER CHAIN, BECAUSE "the model was unreachable" NEEDS A CAUSE ──────
        #
        # When every report starts failing at once the question is always the same: was the
        # spend cap hit, or is a provider misconfigured? Both answers were only in the logs,
        # and one of them (a fallback that failed to construct because its key is missing) was
        # a single line at startup that nobody rereads.
        #
        # A chain of length one is the dangerous state: nothing is wrong until the primary
        # refuses, and then everything is. Reported here so it is visible before that happens
        # rather than diagnosed afterwards.
        "providers": _provider_chain_status(),
        # Cache performance, joined by the SAME `feature` label as the spend above, so
        # "what did this feature cost" and "how often did we avoid paying for it" read
        # side by side. Entries with hit_count 0 are the honest signal that caching a
        # feature bought nothing — a table of those is a table of wasted writes.
        "cache": cache_rows,
        # WHAT THE CACHE COSTS TO KEEP, next to what it saves. `cache` above counts entries
        # and hits; this is disk and the LRU ceiling. Both are needed to answer "should this
        # cache be bigger" — hits alone argue for growth and never for restraint.
        "cache_storage": await vector_cache.storage(db),
        # THE NUMBER THE PRICING DECISION ACTUALLY NEEDS.
        #
        # Everything above answers "what did we spend". This answers "is it getting cheaper
        # per user as more people use it", which is a different question and the only one
        # that says whether a lower price is survivable later.
        #
        # `avoided_usd` prices the cache: hits x what that feature costs per call, per
        # feature, from THIS window's real ledger rather than from a constant in a document.
        # A feature with entries and no hits shows up as zero, which is the honest way to
        # find a cache that is only ever written to.
        "savings": {
            "avoided_usd": round(avoided_total, 6),
            "by_feature": avoided_by_feature,
            # What the bill would have been without the shared cache. The ratio of these two
            # is the whole economies-of-scale claim, expressed as a number somebody can
            # check against an invoice.
            "would_have_cost_usd": round(total_cost + avoided_total, 6),
            "avoided_pct": (
                round(avoided_total / (total_cost + avoided_total) * 100, 1)
                if (total_cost + avoided_total)
                else 0.0
            ),
        },
    }
