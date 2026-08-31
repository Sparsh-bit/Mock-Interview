"""
Anthropic rate-limit headroom at 200 concurrent users — scripts/rate_limit_headroom.py

A SCRIPT RATHER THAN A DOCUMENT, so every assumption is a named constant you can change and
re-run instead of a sentence you have to argue with. Run it:

    cd backend && uv run python scripts/rate_limit_headroom.py

Every number below is one of three things and is labelled as such:

    [CODE]      read from this repository — a setting, a constant, a token budget function
    [MEASURED]  from docs/AI-COST-MODEL.md, which anchors on one logged call
    [ASSUMED]   a judgement about human behaviour that is not in the code at all

The [ASSUMED] rows are where this analysis can be wrong, so they are stated as constants at
the top with the reasoning attached. Nothing here contacts Anthropic or reads an account.
"""

from __future__ import annotations

from dataclasses import dataclass

# ─── The limits themselves ────────────────────────────────────────────────────
#
# Published Anthropic limits for claude-sonnet-5, read from
# https://platform.claude.com/docs/en/api/rate-limits on 2026-08-30. Sonnet 5 has its OWN
# bucket — it is explicitly not pooled with the Sonnet 4.x limit.
#
# TWO PROPERTIES OF THESE LIMITS DO MOST OF THE WORK BELOW:
#
#   * cache_read_input_tokens do NOT count toward ITPM on this model. Only
#     input_tokens + cache_creation_input_tokens do. The GD panel's 2,856-token cached
#     rulebook is therefore free against the rate limit as well as 90% off the bill.
#   * max_tokens does NOT count toward OTPM. Only tokens actually generated. So the
#     report's 12,000-token ceiling is irrelevant here; its measured ~5,580 is what counts.

TIERS: dict[str, tuple[int, int, int]] = {
    #                RPM      ITPM        OTPM
    "Start": (1_000, 2_000_000, 400_000),
    "Build": (5_000, 5_000_000, 1_000_000),
    "Scale": (10_000, 10_000_000, 2_000_000),
}

#: Monthly spend caps per tier, same source. Not a rate limit, but it is the other ceiling
#: and it is the one this product reaches first — see the report at the end.
SPEND_CAPS_USD: dict[str, int] = {"Start": 500, "Build": 1_000, "Scale": 200_000}

# ─── Constants read out of the codebase ───────────────────────────────────────

INTERVIEW_QUESTION_COUNT = 12  # [CODE] core/config.py
INTERVIEW_MAX_CROSS_QUESTIONS = 4  # [CODE] core/config.py
REPORT_CONCURRENCY = 12  # [CODE] core/config.py — PER PROCESS
REPORT_BATCH_SIZE = 6  # [CODE] services/report/composer.py
GD_PANEL_TURNS = 26  # [CODE] the round length api/v1/gd.py is written against

#: [CODE] A report is one summary call plus one call per batch of REPORT_BATCH_SIZE
#: questions — reports.py fans them out with ensure_future. So a 12-question report is
#: THREE provider calls, not one. docs/AI-COST-MODEL.md still prices it as one; that is a
#: costing simplification which is fine for dollars and wrong for RPM.
REPORT_CALLS = 1 + -(-INTERVIEW_QUESTION_COUNT // REPORT_BATCH_SIZE)

# ─── Measured token shapes ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Call:
    """One provider call: what it costs against each of the three limits."""

    name: str
    uncached_input: int  # counts toward ITPM
    cached_input: int  # does NOT count toward ITPM on sonnet-5
    output: int  # counts toward OTPM


# [MEASURED] docs/AI-COST-MODEL.md. The report's 17,059 input is the measured figure for a
# SINGLE-call report; split into REPORT_CALLS the system block is re-sent per call, so the
# real total is higher. Divided evenly here and flagged: this is the one number in the model
# that is an UNDER-estimate, and the direction is stated rather than hidden.
REPORT_TOTAL_INPUT = 17_059
REPORT_TOTAL_OUTPUT = 5_580

REPORT_CALL = Call(
    "report_generation",
    uncached_input=REPORT_TOTAL_INPUT // REPORT_CALLS,
    cached_input=0,
    output=REPORT_TOTAL_OUTPUT // REPORT_CALLS,
)

# [MEASURED] The GD panel turn, with prompt caching on. 2,856 tokens of static rulebook are
# a cache READ on 25 of the 26 turns — free against ITPM — and 336 tokens are not.
GD_TURN_CALL = Call("gd_panel_turn", uncached_input=336, cached_input=2_856, output=350)

# [MEASURED] Interview plan: one call at session start. [CODE] max_tokens is
# plan_token_budget(12) = 3,820.
PLAN_CALL = Call("interview_plan", uncached_input=2_536, cached_input=0, output=3_820)

# [MEASURED] A live follow-up. Small in both directions.
CROSS_CALL = Call("cross_question", uncached_input=1_093, cached_input=0, output=300)

# ─── Behaviour: the assumptions, isolated ─────────────────────────────────────

#: [ASSUMED] What "200 concurrent users" means. THE MOST IMPORTANT ASSUMPTION IN THE FILE.
#: Taken as 200 people with a session OPEN at the same moment — not 200 requests in flight.
#: The distinction is roughly two orders of magnitude: a candidate spends most of an
#: interview reading and typing, not waiting on the model. If the intended meaning were 200
#: simultaneous in-flight calls, every conclusion below changes and the answer is simply
#: "far past Start tier".
CONCURRENT_USERS = 200

#: [ASSUMED] Seconds a candidate spends per interview exchange — reading the question,
#: typing an answer, submitting. 90s is a deliberately BRISK estimate: too low here
#: overstates the request rate, which is the safe direction for a headroom analysis.
SECONDS_PER_INTERVIEW_EXCHANGE = 90

#: [MEASURED] docs/AI-COST-MODEL.md states a panel turn every ~18 seconds keeps the 5-minute
#: prompt cache warm across a round, which fixes the GD call rate without assuming anything.
SECONDS_PER_GD_TURN = 18

#: [MEASURED] A report takes ~21s wall clock (the figure REPORT_CONCURRENCY was sized
#: against, in the note above _report_slots).
REPORT_SECONDS = 21

#: [ASSUMED] The mix. Campus prep, so a cohort is doing broadly the same thing at the same
#: time — which is itself the risk, and why the correlated-peak scenario exists separately.
#: `idle_or_quiz` makes no metered Anthropic call: quizzes are unlimited on every tier and
#: served from the banks in app/data, so those users cost nothing against these limits.
MIX = {"interview": 0.60, "gd": 0.25, "idle_or_quiz": 0.15}

#: [CODE] settings.PROCESS_COUNT — WEB_REPLICA_COUNT x WEB_CONCURRENCY. The fleet-wide report
#: concurrency is this times REPORT_CONCURRENCY, which is what actually bounds the report
#: burst.
#:
#: IT COUNTS PROCESSES, NOT CONTAINERS, and the distinction is the whole reason PROCESS_COUNT
#: exists. `_report_slots` is a per-process semaphore, so four uvicorn workers inside one
#: replica are four independent semaphores and four times the provider-facing concurrency —
#: identical to four replicas as far as Anthropic's buckets are concerned. Reading the replica
#: count alone would report a quarter of the real peak and call it headroom.
REPLICAS = 1


# ─── The model ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Load:
    rpm: float
    itpm: float
    otpm: float

    def __add__(self, other: Load) -> Load:
        return Load(self.rpm + other.rpm, self.itpm + other.itpm, self.otpm + other.otpm)


def sustained(call: Call, calls_per_minute: float, *, first_call_writes_cache: bool = False) -> Load:
    """
    Load from making `call` at `calls_per_minute`.

    Cached input is excluded from ITPM — that is the model's documented behaviour, not an
    optimism. `first_call_writes_cache` charges the cache WRITE, which does count, amortised
    across a GD round.
    """
    itpm = call.uncached_input * calls_per_minute
    if first_call_writes_cache:
        itpm += call.cached_input * (calls_per_minute / GD_PANEL_TURNS)
    return Load(calls_per_minute, itpm, call.output * calls_per_minute)


def steady_state() -> tuple[Load, list[str]]:
    """200 users spread across the mix, each mid-session."""
    notes: list[str] = []
    interviewers = CONCURRENT_USERS * MIX["interview"]
    gd_users = CONCURRENT_USERS * MIX["gd"]

    # An interview session is 12 questions + up to 4 cross-questions. The plan is ONE call at
    # the start and pre-generates every question, so the steady rate during a session is just
    # the cross-questions — which is why interviews are cheap in RPM and expensive in bursts.
    exchanges = INTERVIEW_QUESTION_COUNT + INTERVIEW_MAX_CROSS_QUESTIONS
    session_minutes = exchanges * SECONDS_PER_INTERVIEW_EXCHANGE / 60
    plan_rate = interviewers * (1 / session_minutes)
    cross_rate = interviewers * (INTERVIEW_MAX_CROSS_QUESTIONS / session_minutes)
    # One report per session, REPORT_CALLS provider calls each.
    report_rate = interviewers * (REPORT_CALLS / session_minutes)
    notes.append(
        f"interview session = {exchanges} exchanges x {SECONDS_PER_INTERVIEW_EXCHANGE}s "
        f"= {session_minutes:.0f} min"
    )

    gd_rate = gd_users * (60 / SECONDS_PER_GD_TURN)
    notes.append(f"GD = one turn every {SECONDS_PER_GD_TURN}s per active user")

    total = (
        sustained(PLAN_CALL, plan_rate)
        + sustained(CROSS_CALL, cross_rate)
        + sustained(REPORT_CALL, report_rate)
        + sustained(GD_TURN_CALL, gd_rate, first_call_writes_cache=True)
    )
    return total, notes


def correlated_report_peak() -> tuple[Load, list[str]]:
    """
    The scenario that actually breaks, and the reason a steady-state average is not enough.

    A campus cohort starts together and therefore FINISHES together, so reports do not
    arrive as a Poisson trickle — they arrive as a wall. What bounds that wall is not the
    provider, it is `_report_slots`: REPORT_CONCURRENCY per process, times the replica count.
    The semaphore IS the rate limiter, which is worth knowing before anyone raises it.
    """
    in_flight = REPORT_CONCURRENCY * REPLICAS
    reports_per_minute = in_flight * (60 / REPORT_SECONDS)
    load = Load(
        rpm=reports_per_minute * REPORT_CALLS,
        itpm=reports_per_minute * REPORT_TOTAL_INPUT,
        otpm=reports_per_minute * REPORT_TOTAL_OUTPUT,
    )
    notes = [
        f"{in_flight} reports in flight ({REPORT_CONCURRENCY} x {REPLICAS} replicas)",
        f"each ~{REPORT_SECONDS}s -> {reports_per_minute:.0f} reports/min",
        f"x {REPORT_CALLS} provider calls each (summary + "
        f"{REPORT_CALLS - 1} batches of {REPORT_BATCH_SIZE})",
    ]
    return load, notes


def _bar(pct: float) -> str:
    filled = min(int(pct / 5), 20)
    flag = "  <-- OVER" if pct > 100 else ("  <-- tight" if pct >= 80 else "")
    return f"[{'#' * filled}{'.' * (20 - filled)}] {pct:5.1f}%{flag}"


def report(title: str, load: Load, notes: list[str]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for n in notes:
        print(f"  {n}")
    print(f"\n  peak RPM  {load.rpm:>10,.0f}")
    print(f"  peak ITPM {load.itpm:>10,.0f}   (uncached input only — cache reads are free)")
    print(f"  peak OTPM {load.otpm:>10,.0f}")
    print()
    for tier, (rpm, itpm, otpm) in TIERS.items():
        print(f"  {tier:<6} RPM  {_bar(100 * load.rpm / rpm)}")
        print(f"  {'':<6} ITPM {_bar(100 * load.itpm / itpm)}")
        print(f"  {'':<6} OTPM {_bar(100 * load.otpm / otpm)}")
        print()


def main() -> None:
    print(__doc__)
    print(f"REPLICAS = {REPLICAS}   CONCURRENT_USERS = {CONCURRENT_USERS}")

    steady, steady_notes = steady_state()
    report("SCENARIO A — 200 concurrent users, steady state", steady, steady_notes)

    peak, peak_notes = correlated_report_peak()
    report("SCENARIO B — a cohort's reports land together", peak, peak_notes)

    print("\nBINDING CONSTRAINT")
    print("------------------")
    for label, load in (("A steady", steady), ("B peak", peak)):
        worst = max(
            ("RPM", 100 * load.rpm / TIERS["Start"][0]),
            ("ITPM", 100 * load.itpm / TIERS["Start"][1]),
            ("OTPM", 100 * load.otpm / TIERS["Start"][2]),
            key=lambda x: x[1],
        )
        print(f"  {label:<9} on Start tier: {worst[0]} at {worst[1]:.0f}% of limit")

    print("\n  Neither is RPM. Output tokens are the scarce resource, because this product's")
    print("  expensive call is one that WRITES a lot — and OTPM is one fifth of ITPM on")
    print("  every tier. Scenario B at REPLICAS=2 is the number to watch:")
    for r in (1, 2, 3, 4):
        rpm_ = REPORT_CONCURRENCY * r * (60 / REPORT_SECONDS)
        otpm_ = rpm_ * REPORT_TOTAL_OUTPUT
        print(
            f"    {r} replica(s): {otpm_:>9,.0f} OTPM = "
            f"{100 * otpm_ / TIERS['Start'][2]:5.1f}% of Start tier's {TIERS['Start'][2]:,}"
        )

    print("\nTHE OTHER CEILING")
    print("-----------------")
    print("  Rate limits are not the first thing this product hits. The Start tier's monthly")
    print(f"  spend cap is ${SPEND_CAPS_USD['Start']}, and a warm interview costs $0.1544")
    print("  (docs/AI-COST-MODEL.md), so the cap is about")
    print(f"    {SPEND_CAPS_USD['Start'] / 0.1544:,.0f} interviews a month "
          f"= {SPEND_CAPS_USD['Start'] / 0.1544 / 30:,.0f} a day")
    print("  — reached long before 200 concurrent users are sustained. AI_DAILY_BUDGET_USD")
    print("  defaults to $60/day, which is $1,800/month: ALREADY OVER the Start cap and over")
    print("  Build's $1,000. That is the ceiling to plan against, not RPM.")


if __name__ == "__main__":
    main()
