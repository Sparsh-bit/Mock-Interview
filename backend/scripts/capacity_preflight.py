#!/usr/bin/env python
"""
Will this deployment serve N concurrent candidates? — scripts/capacity_preflight.py

    cd backend && uv run python scripts/capacity_preflight.py --users 200

WHY THIS IS A SCRIPT AND NOT A TABLE IN A DOCUMENT. Every capacity claim about this product is
arithmetic over values in core/config.py, and a table decays silently: raise REPORT_CONCURRENCY
to make reports faster, or add a worker to use more CPU, and the document keeps asserting a
headroom that stopped being true an hour ago. This reads the live settings and recomputes.
docs/RAILWAY.md carries the same rows; if the two ever disagree, believe this one.

WHAT IT DOES NOT DO. It contacts nothing and measures nothing — no Redis, no database, no
provider. It is arithmetic over configuration plus the measured per-feature figures in
docs/AI-COST-MODEL.md, so it can tell you a pool is too small for a load and it CANNOT tell
you the host has enough CPU. Only a load test answers that.

TWO DIFFERENT QUESTIONS, DELIBERATELY BOTH ANSWERED. The connection and rate-limit checks are
about a CONCURRENT SNAPSHOT — how many people have a session open at this moment. The spend
checks are about a DAY'S TOTAL — what N candidates cost if each does one interview and one
group discussion. Mixing them up is the easiest way to be confidently wrong here, so each
check says which it is.

Related: docs/RAILWAY.md · docs/RATE-LIMIT-HEADROOM.md · docs/AI-COST-MODEL.md
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.redis import audit_redis_configuration  # noqa: E402
from app.db.session import audit_db_connection_budget  # noqa: E402

# ─── The load model ───────────────────────────────────────────────────────────
#
# PINNED AGAINST scripts/rate_limit_headroom.py by tests/test_capacity_preflight.py. Two tools
# describing one deployment must not disagree about how busy a candidate is.

#: [ASSUMED] Human pacing, not code. Brisk on purpose: too low OVERSTATES the request rate,
#: which is the safe direction for a headroom estimate.
SECONDS_PER_INTERVIEW_EXCHANGE = 90

#: [ASSUMED] A campus cohort does broadly the same thing at the same time — which is itself the
#: risk. `idle_or_quiz` costs nothing here: quizzes are served from the banks in app/data.
MIX = {"interview": 0.60, "gd": 0.25, "idle_or_quiz": 0.15}

#: [MEASURED] Wall clock for one report, the figure REPORT_CONCURRENCY was sized against.
REPORT_SECONDS = 21

#: [MEASURED] docs/AI-COST-MODEL.md — output is what the report is bound by.
REPORT_TOTAL_OUTPUT = 5_580

#: [PUBLISHED] Anthropic Start tier output tokens per minute. The binding constraint for this
#: product, because its expensive call is one that WRITES a lot and OTPM is a fifth of ITPM on
#: every tier. Checked against Start because that is the floor worth designing for.
START_TIER_OTPM = 400_000

#: Output tokens a minute one report slot can produce flat out.
OTPM_PER_REPORT_SLOT = (60 / REPORT_SECONDS) * REPORT_TOTAL_OUTPUT

#: [MEASURED] docs/AI-COST-MODEL.md. Warm = the interview plan cache hit, which is the normal
#: case; the report is 58% of it and batching halves the report.
INTERVIEW_USD = 0.1544
GD_ROUND_USD = 0.142

#: What fraction of a WARM interview the report is — the part the batch API halves.
#:
#: 0.80, NOT THE 0.58 THE COST MODEL HEADLINES. That 58% is measured against the COLD
#: interview ($0.1349 of $0.2309), where the interview plan is also being paid for. Against
#: the WARM interview — the normal case, where the plan is a cache hit — the report is $0.1233
#: of $0.1544, because report + cross-questions is the whole of it: $0.1233 + $0.0311.
#:
#: Applying the cold share to the warm figure halved 58% instead of 80% and overstated the
#: daily bill by ~18%. Conservative, and still wrong: a capacity tool that errs safe still
#: sets budgets to the wrong number.
REPORT_SHARE_OF_INTERVIEW = 0.1233 / 0.1544

#: [MEASURED] docs/ELEVENLABS-SETUP.md, ~7,800 characters a GD round.
TTS_USD_PER_GD_ROUND = {"fish": 0.117, "elevenlabs": 1.72, "azure": 0.12, "google": 0.13}
TTS_USD_PER_INTERVIEW = {"fish": 0.048, "elevenlabs": 0.63, "azure": 0.04, "google": 0.05}

#: Warn rather than pass when a budget is this close to the load. A ceiling reached at 95% is
#: a ceiling reached on the first busy Tuesday.
_HEADROOM_WARN_RATIO = 0.85


@dataclass(frozen=True)
class Check:
    """One ceiling, its arithmetic, and whether the target clears it."""

    name: str
    ok: bool
    detail: str
    #: True when failing it means the target is NOT served. False = worth knowing, not fatal.
    fatal: bool = True

    @property
    def status(self) -> str:
        if self.ok:
            return "PASS"
        return "FAIL" if self.fatal else "WARN"


# ─── Per-feature worst case ───────────────────────────────────────────────────
#
# THE QUESTION THE MIX SCENARIO DOES NOT ANSWER. `assess()` models a cohort doing broadly what
# a cohort does — 60% interviewing, 25% in a group discussion, 15% idle. A SCHEDULED ACTIVITY
# is not that shape: 150 people all starting a group discussion at the same moment puts every
# one of them on one feature, and the per-user call rate that was a quarter of the load becomes
# all of it.
#
# MEASURED FIGURES ONLY, AND THE REST SAY SO. Four features have per-call token counts in
# docs/AI-COST-MODEL.md. The others do not, and an unmeasured row reported as PASS would be
# worse than an absent one — so they are listed with `measured=False` and no verdict.

#: [PUBLISHED] Anthropic Start-tier limits, per model. Rate limits are per-model and not
#: pooled, so these apply to whatever ANTHROPIC_MODEL names.
START_TIER = {"rpm": 1_000, "itpm": 2_000_000, "otpm": 400_000}


@dataclass(frozen=True)
class FeatureLoad:
    """One feature, at the target load, with every user on it at once."""

    feature: str
    ok: bool
    measured: bool
    rpm: float
    itpm: float
    otpm: float
    usd_per_user: float
    detail: str


#: Per-user call shape for the features whose tokens are measured.
#:
#: `seconds_between` is how often ONE user triggers the call while active; `calls_per_session`
#: is how many that user makes in total. Uncached input only — cache reads do not count toward
#: ITPM (docs/RATE-LIMIT-HEADROOM.md), which is why the GD panel's 2,856-token rulebook is
#: absent from its input figure.
_MEASURED_FEATURES = [
    {
        "feature": "gd",
        "label": "Group discussion (panel turns)",
        "seconds_between": 18.0,
        "input": 336,
        "output": 350,
        "usd_per_user": GD_ROUND_USD,
    },
    {
        "feature": "interview",
        "label": "Interview (question path)",
        # One exchange every 90s; a cross-question falls on every third answer, so the
        # AI-bearing share of exchanges is a third.
        "seconds_between": 90.0 / (1 / 3),
        "input": 1_093,
        "output": 300,
        "usd_per_user": INTERVIEW_USD,
    },
]

#: Features with no measured token figures. Listed rather than omitted, because a capacity
#: table that silently covers only what was easy to measure reads as complete.
_UNMEASURED_FEATURES = [
    ("quiz", "Quiz", "served from the curated banks in app/data first; the AI path only tops up a shortfall"),
    ("communication", "Communication round", "communication_evaluation + communication_cross_question"),
    ("coding", "Coding round", "code_analysis + panel_code_review, plus Judge0 for execution"),
    ("resume", "Resume analysis", "resume_analysis_skills + resume_analysis_projects, 35s budget"),
]


def assess_features(cfg, users: int) -> list[FeatureLoad]:
    """Every feature at `users` concurrent, as if all of them were on that one feature."""
    rows: list[FeatureLoad] = []

    for f in _MEASURED_FEATURES:
        per_second = users / f["seconds_between"]
        rpm = per_second * 60
        itpm = per_second * f["input"] * 60
        otpm = per_second * f["output"] * 60
        # OTPM is the binding limit on this product — its expensive calls write a lot, and
        # OTPM is a fifth of ITPM on every tier.
        worst = max(rpm / START_TIER["rpm"], itpm / START_TIER["itpm"], otpm / START_TIER["otpm"])
        rows.append(
            FeatureLoad(
                feature=f["feature"],
                ok=worst <= _HEADROOM_WARN_RATIO,
                measured=True,
                rpm=rpm,
                itpm=itpm,
                otpm=otpm,
                usd_per_user=f["usd_per_user"],
                detail=(
                    f"{f['label']}: {users} users x 1 call / {f['seconds_between']:.0f}s = "
                    f"{rpm:,.0f} RPM, {itpm:,.0f} ITPM, {otpm:,.0f} OTPM "
                    f"({100 * worst:.0f}% of the Start tier's tightest limit)"
                ),
            )
        )

    for key, label, why in _UNMEASURED_FEATURES:
        rows.append(
            FeatureLoad(
                feature=key,
                ok=True,
                measured=False,
                rpm=0.0,
                itpm=0.0,
                otpm=0.0,
                usd_per_user=0.0,
                detail=f"{label}: not measured — {why}. Add token counts to docs/AI-COST-MODEL.md to assess it.",
            )
        )

    return rows


def assess(cfg, users: int) -> list[Check]:
    """
    Every ceiling this tool knows about, computed against `cfg` at `users` concurrent.

    `cfg` is a Settings (or anything carrying the same attribute names), so a caller can ask
    the question about a configuration that is not the one this process booted with.
    """
    processes = cfg.WEB_REPLICA_COUNT * cfg.WEB_CONCURRENCY
    checks: list[Check] = []

    # ── 1. Connections the live load needs, against the pool it has ──────────────────────
    #
    # A CONCURRENT SNAPSHOT. Little's law: connections held = arrival rate x hold time.
    #
    # The interview question path is the whole term. Panel and GD turns commit before their
    # model call (api/v1/panel.py), so they hold a connection for milliseconds; report
    # generation does the same (api/v1/reports.py). `get_next_question` does not, so it holds
    # one for as long as its model call runs — and that is what this measures, at the WORST
    # case where every call runs to its full budget.
    interview_users = users * MIX["interview"]
    question_rate = interview_users / SECONDS_PER_INTERVIEW_EXCHANGE
    needed = question_rate * cfg.INTERVIEW_QUESTION_AI_BUDGET_SECONDS
    have = (cfg.DB_POOL_SIZE + cfg.DB_MAX_OVERFLOW) * processes
    checks.append(
        Check(
            name="db_connections_for_load",
            ok=needed <= have * _HEADROOM_WARN_RATIO,
            detail=(
                f"{interview_users:.0f} in interviews / {SECONDS_PER_INTERVIEW_EXCHANGE}s "
                f"x {cfg.INTERVIEW_QUESTION_AI_BUDGET_SECONDS:.0f}s budget = "
                f"{needed:.1f} connections held at worst; pool is "
                f"({cfg.DB_POOL_SIZE} + {cfg.DB_MAX_OVERFLOW}) x {processes} processes = {have}"
            ),
        )
    )

    # ── 1b. THE POOLER'S SERVER CONNECTIONS — the tightest ceiling in the system ─────────
    #
    # Not the same question as the check above, and this is the one that was missing. That one
    # asks whether the app's own pool has enough slots. This asks whether POSTGRES will give
    # the pooler enough backends to satisfy them: in transaction mode every open transaction
    # occupies one of `DB_POOLER_POOL_SIZE` for as long as it is open, and past that requests
    # queue inside the pooler where this process cannot see them.
    #
    # IT DOES NOT MULTIPLY BY PROCESS_COUNT, deliberately and unlike everything else here.
    # The pooler's pool belongs to the database, so four workers share one set of 15 — which
    # means adding compute cannot fix this check, and that is exactly why it is worth its own
    # line rather than being folded into the one above.
    if cfg.DB_POOLER_POOL_SIZE <= 0:
        checks.append(
            Check(
                name="pooler_server_connections",
                ok=True,
                detail=(
                    "DB_POOLER_POOL_SIZE is UNSET, so the tightest ceiling is not assessed. "
                    "Supabase -> Settings -> Database -> Connection pooling -> "
                    '"Connection pool size"'
                ),
                fatal=False,
            )
        )
    else:
        checks.append(
            Check(
                name="pooler_server_connections",
                ok=needed <= cfg.DB_POOLER_POOL_SIZE * _HEADROOM_WARN_RATIO,
                detail=(
                    f"{needed:.1f} simultaneous open transactions at worst against the "
                    f"pooler's {cfg.DB_POOLER_POOL_SIZE} Postgres connections "
                    f"(shared by ALL {processes} process(es) — this one does not multiply)"
                ),
            )
        )

    # ── 2 & 3. The two fleet ceilings the app already audits at startup ──────────────────
    #
    # REUSED, not reimplemented: these are the same functions the lifespan logs, so this tool
    # cannot drift from what the running process will tell you.
    db_issues = audit_db_connection_budget(
        pool_size=cfg.DB_POOL_SIZE,
        max_overflow=cfg.DB_MAX_OVERFLOW,
        replicas=processes,
        ceiling=cfg.DB_CONNECTION_CEILING,
    )
    over = [i for i in db_issues if "over_ceiling" in i.code]
    checks.append(
        Check(
            name="db_pooler_ceiling",
            ok=not over,
            detail=(
                over[0].message
                if over
                else f"{have} connections against a pooler ceiling of "
                + (
                    str(cfg.DB_CONNECTION_CEILING)
                    if cfg.DB_CONNECTION_CEILING
                    else "UNSET — nothing is checked"
                )
            ),
            fatal=bool(over),
        )
    )

    redis_issues = audit_redis_configuration(
        url=cfg.REDIS_URL,
        environment=cfg.ENVIRONMENT,
        max_connections=cfg.REDIS_MAX_CONNECTIONS,
        replicas=processes,
        ceiling=cfg.REDIS_CONNECTION_CEILING,
    )
    r_over = [i for i in redis_issues if "over_ceiling" in i.code]
    checks.append(
        Check(
            name="redis_connection_ceiling",
            ok=not r_over,
            detail=(
                r_over[0].message
                if r_over
                else f"{cfg.REDIS_MAX_CONNECTIONS} x {processes} processes = "
                f"{cfg.REDIS_MAX_CONNECTIONS * processes} against a ceiling of "
                + (
                    str(cfg.REDIS_CONNECTION_CEILING)
                    if cfg.REDIS_CONNECTION_CEILING
                    else "UNSET — nothing is checked"
                )
            ),
            fatal=bool(r_over),
        )
    )

    # ── 4. The report semaphore IS the provider rate limiter ─────────────────────────────
    #
    # docs/RATE-LIMIT-HEADROOM.md's central finding. What bounds the report burst is not the
    # provider, it is REPORT_CONCURRENCY per process — so this number scales with workers and
    # replicas, and at the old default of 12 the second process already reached 96% of Start.
    slots = cfg.REPORT_CONCURRENCY * processes
    otpm = slots * OTPM_PER_REPORT_SLOT
    pct = 100 * otpm / START_TIER_OTPM
    checks.append(
        Check(
            name="report_output_tokens_per_minute",
            ok=otpm <= START_TIER_OTPM * _HEADROOM_WARN_RATIO,
            detail=(
                f"{cfg.REPORT_CONCURRENCY} x {processes} processes = {slots} slots = "
                f"{otpm:,.0f} OTPM, {pct:.0f}% of the Start tier's {START_TIER_OTPM:,}"
            ),
        )
    )

    # ── 5. A DAY'S SPEND, which is a different question from everything above ────────────
    #
    # N candidates each doing one interview and one group discussion. The batch API halves the
    # report, and the report is 58% of an interview.
    interview_cost = INTERVIEW_USD
    if getattr(cfg, "REPORT_BATCH_ENABLED", False):
        interview_cost -= INTERVIEW_USD * REPORT_SHARE_OF_INTERVIEW * 0.5
    daily = users * (interview_cost + GD_ROUND_USD)
    checks.append(
        Check(
            name="ai_daily_budget",
            ok=daily <= cfg.AI_DAILY_BUDGET_USD * _HEADROOM_WARN_RATIO,
            detail=(
                f"{users} x (${interview_cost:.4f} interview"
                f"{' batched' if getattr(cfg, 'REPORT_BATCH_ENABLED', False) else ''}"
                f" + ${GD_ROUND_USD:.3f} GD) = ${daily:.2f}/day against "
                f"AI_DAILY_BUDGET_USD ${cfg.AI_DAILY_BUDGET_USD:.2f}"
            ),
        )
    )

    # ── 6. Speech, which is priced per character and can dwarf everything else ───────────
    if getattr(cfg, "TTS_ENABLED", False):
        vendor = (cfg.TTS_PROVIDER or "").lower().strip()
        per_gd = TTS_USD_PER_GD_ROUND.get(vendor)
        per_interview = TTS_USD_PER_INTERVIEW.get(vendor)
        if per_gd is None or per_interview is None:
            checks.append(
                Check(
                    name="tts_daily_budget",
                    ok=True,
                    detail=f"TTS_PROVIDER '{vendor}' has no price on file — not assessed",
                    fatal=False,
                )
            )
        else:
            tts_daily = users * (per_gd + per_interview)
            checks.append(
                Check(
                    name="tts_daily_budget",
                    ok=tts_daily <= cfg.TTS_DAILY_BUDGET_USD * _HEADROOM_WARN_RATIO,
                    detail=(
                        f"{users} x (${per_gd:.3f} GD + ${per_interview:.3f} interview) on "
                        f"{vendor} = ${tts_daily:.2f}/day against TTS_DAILY_BUDGET_USD "
                        f"${cfg.TTS_DAILY_BUDGET_USD:.2f}"
                    ),
                )
            )
    else:
        checks.append(
            Check(name="tts_daily_budget", ok=True, detail="TTS is off", fatal=False)
        )

    # ── 7. The shared free code runner ───────────────────────────────────────────────────
    #
    # RATE_LIMIT_CODE_EXEC_PER_MINUTE is per USER and says nothing about N of them. The public
    # Judge0 CE instance is free and shared with the whole internet, and the way a drive aimed
    # at it ends is a blocked egress IP rather than a slowdown.
    provider = (cfg.CODE_EXEC_PROVIDER or "").lower().strip()
    if provider != "judge0" or cfg.JUDGE0_API_KEY:
        checks.append(
            Check(
                name="code_execution",
                ok=True,
                detail=(
                    f"{provider}"
                    + (" with a paid key — not capped by the free-tier guard" if cfg.JUDGE0_API_KEY else "")
                ),
                fatal=False,
            )
        )
    else:
        capped = cfg.JUDGE0_DAILY_REQUEST_LIMIT > 0
        checks.append(
            Check(
                name="code_execution",
                ok=capped,
                detail=(
                    f"public Judge0 CE, fleet cap {cfg.JUDGE0_DAILY_REQUEST_LIMIT}/day"
                    if capped
                    else "public Judge0 CE with JUDGE0_DAILY_REQUEST_LIMIT=0 — no fleet cap "
                    "on a free shared service; set a limit or a JUDGE0_API_KEY"
                ),
            )
        )

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=200, help="concurrent candidates")
    args = parser.parse_args()

    from app.core.config import settings

    checks = assess(settings, args.users)
    width = max(len(c.name) for c in checks)

    print(f"\nCAPACITY PREFLIGHT — {args.users} concurrent candidates")
    print(
        f"  {settings.WEB_REPLICA_COUNT} replica(s) x {settings.WEB_CONCURRENCY} worker(s) "
        f"= {settings.PROCESS_COUNT} process(es)\n"
    )
    for c in checks:
        print(f"  [{c.status:<4}] {c.name:<{width}}  {c.detail}")

    fatal = [c for c in checks if not c.ok and c.fatal]
    warn = [c for c in checks if not c.ok and not c.fatal]
    print()
    if fatal:
        print(f"  {len(fatal)} blocking issue(s). This configuration will not serve "
              f"{args.users} concurrent candidates.")
    elif warn:
        print(f"  No blocking issues. {len(warn)} thing(s) worth knowing above.")
    else:
        print(f"  Every ceiling checked clears {args.users} concurrent candidates.")
    print("\n  Arithmetic only — nothing here proves the host has the CPU. Load-test that.\n")
    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
