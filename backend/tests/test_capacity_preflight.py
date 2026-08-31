"""
The capacity claim is checkable, not quotable — tests/test_capacity_preflight.py

WHY A SCRIPT AND NOT A DOCUMENT. docs/RAILWAY.md carries a table of settings for 200
concurrent candidates, and every row of it is arithmetic over values that live in
core/config.py. A table decays silently: somebody raises REPORT_CONCURRENCY to make reports
faster, or adds a worker to use more CPU, and the document keeps asserting a headroom that
stopped being true. `scripts/capacity_preflight.py` computes the same rows from the live
settings, so the answer is derived rather than remembered — the same reason
scripts/rate_limit_headroom.py exists and says "meant to be run, not quoted".

WHAT IS PINNED HERE. The load model constants must agree with the headroom analysis, or the
two tools would give different answers about the same deployment and both would look
authoritative.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.core.config import Settings

REPO_BACKEND = Path(__file__).resolve().parents[1]


def _load(name: str):
    path = REPO_BACKEND / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def preflight():
    return _load("capacity_preflight")


@pytest.fixture(scope="module")
def headroom():
    return _load("rate_limit_headroom")


def _cfg(**overrides):
    """The documented 200-user configuration, unless a test changes one value."""
    base = {
        "WEB_REPLICA_COUNT": 1,
        "WEB_CONCURRENCY": 4,
        "DB_POOL_SIZE": 5,
        "DB_MAX_OVERFLOW": 10,
        "DB_CONNECTION_CEILING": 200,
        "DB_POOLER_POOL_SIZE": 40,
        "REDIS_MAX_CONNECTIONS": 15,
        "REDIS_CONNECTION_CEILING": 100,
        "REDIS_URL": "rediss://default:x@fake.upstash.io:6379",
        "ENVIRONMENT": "production",
        "REPORT_CONCURRENCY": 4,
        "REPORT_BATCH_ENABLED": True,
        "AI_DAILY_BUDGET_USD": 75.0,
        "TTS_ENABLED": True,
        "TTS_DAILY_BUDGET_USD": 40.0,
        "TTS_PROVIDER": "fish",
        "CODE_EXEC_PROVIDER": "judge0",
        "JUDGE0_API_KEY": "",
        "JUDGE0_DAILY_REQUEST_LIMIT": 3000,
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def _by_name(checks):
    return {c.name: c for c in checks}


class TestTheDocumentedConfigurationPasses:
    def test_two_hundred_users_pass_on_the_documented_settings(self, preflight):
        """
        The table in docs/RAILWAY.md claims this config serves 200. If this fails, either the
        table is wrong or the defaults moved underneath it — both worth knowing.
        """
        checks = preflight.assess(_cfg(), users=200)
        failed = [c.name for c in checks if not c.ok and c.fatal]
        assert failed == [], f"documented 200-user config does not pass: {failed}"

    def test_it_reports_every_ceiling_it_knows_about(self, preflight):
        """A preflight that silently skips a check is worse than no preflight."""
        names = set(_by_name(preflight.assess(_cfg(), users=200)))
        assert {
            "db_connections_for_load",
            "db_pooler_ceiling",
            "pooler_server_connections",
            "redis_connection_ceiling",
            "report_output_tokens_per_minute",
            "ai_daily_budget",
            "tts_daily_budget",
            "code_execution",
        } <= names


class TestItCatchesEachCeiling:
    def test_a_pool_too_small_for_the_load_fails(self, preflight):
        check = _by_name(preflight.assess(_cfg(WEB_CONCURRENCY=1), users=200))[
            "db_connections_for_load"
        ]
        # (5 + 10) x 1 process = 15 connections against ~24 needed at full budget.
        assert check.ok is False
        assert check.fatal is True
        assert "15" in check.detail

    def test_report_concurrency_over_the_provider_tier_fails(self, preflight):
        """The binding constraint from docs/RATE-LIMIT-HEADROOM.md: the semaphore IS the limiter."""
        check = _by_name(preflight.assess(_cfg(REPORT_CONCURRENCY=12), users=200))[
            "report_output_tokens_per_minute"
        ]
        # 12 x 4 processes = 48 slots, which is 191% of the Start tier's 400,000 OTPM.
        assert check.ok is False

    def test_a_daily_budget_under_the_load_fails(self, preflight):
        check = _by_name(preflight.assess(_cfg(AI_DAILY_BUDGET_USD=20.0), users=200))[
            "ai_daily_budget"
        ]
        assert check.ok is False
        assert "$" in check.detail

    def test_elevenlabs_at_this_volume_fails(self, preflight):
        """$1.72 a GD round is $344/day at 200 users — 87% of total spend."""
        check = _by_name(
            preflight.assess(_cfg(TTS_PROVIDER="elevenlabs"), users=200)
        )["tts_daily_budget"]
        assert check.ok is False

    def test_an_uncapped_free_judge0_is_flagged(self, preflight):
        check = _by_name(
            preflight.assess(_cfg(JUDGE0_DAILY_REQUEST_LIMIT=0), users=200)
        )["code_execution"]
        assert check.ok is False

    def test_a_paid_judge0_key_needs_no_cap(self, preflight):
        """THE VACUITY GUARD: the flag above must be about the FREE instance, not about judge0."""
        check = _by_name(
            preflight.assess(
                _cfg(JUDGE0_DAILY_REQUEST_LIMIT=0, JUDGE0_API_KEY="a-key"), users=200
            )
        )["code_execution"]
        assert check.ok is True

    def test_batching_off_costs_more_and_is_reported_as_such(self, preflight):
        """
        Reports are 58% of an interview and batching halves them. Turning it off must move the
        spend figure, or the check is not reading the setting at all.
        """
        on = _by_name(preflight.assess(_cfg(), users=200))["ai_daily_budget"]
        off = _by_name(preflight.assess(_cfg(REPORT_BATCH_ENABLED=False), users=200))[
            "ai_daily_budget"
        ]
        assert off.detail != on.detail


class TestThePoolerServerConnectionsAreTheRealCeiling:
    """
    THE CONSTRAINT THAT WAS BEING MISSED, AND IT IS THE TIGHTEST ONE.

    Supabase's pooler has two different numbers and they are easy to confuse:

      Max client connections  how many clients may connect TO the pooler. 200 on Nano, fixed.
      Connection pool size    how many connections the pooler opens to ACTUAL POSTGRES,
                              shared across every client. 15 on Nano by default.

    In transaction mode an idle application connection costs ZERO Postgres connections — but
    one holding an OPEN TRANSACTION occupies one of those 15 for as long as it is open. So the
    ceiling on concurrency is not the app's pool (60), and not the client limit (200). It is 15
    simultaneous open transactions, and past it requests queue inside the pooler where this
    application cannot see them.

    The preflight originally checked only the client limit, which is the loosest of the three
    and therefore the least useful.
    """

    def test_the_nano_default_of_15_cannot_serve_two_hundred(self, preflight):
        """
        THE FINDING THIS CHECK WAS ADDED FOR. 120 interview users / 90s x an 18s worst-case
        budget = 24 simultaneous open transactions, against the 15 Postgres connections a
        Supabase Nano pooler holds by default. The documented configuration therefore has to
        raise the pool size; no amount of application tuning reaches it.
        """
        check = _by_name(preflight.assess(_cfg(DB_POOLER_POOL_SIZE=15), users=200))[
            "pooler_server_connections"
        ]
        assert check.ok is False
        assert check.fatal is True
        assert "15" in check.detail

    def test_a_bigger_pooler_pool_clears_it(self, preflight):
        """
        THE VACUITY GUARD, and also the real remedy: the pool size field is editable, so
        raising it (bounded by Postgres's own max_connections) is a legitimate fix.
        """
        check = _by_name(preflight.assess(_cfg(DB_POOLER_POOL_SIZE=40), users=200))[
            "pooler_server_connections"
        ]
        assert check.ok is True

    def test_it_is_not_assessed_when_the_pool_size_is_unknown(self, preflight):
        """
        Same rule as every other ceiling in this codebase: no guessed default. 0 means nobody
        has read it off the dashboard, and the check says so rather than inventing a number.
        """
        check = _by_name(preflight.assess(_cfg(DB_POOLER_POOL_SIZE=0), users=200))[
            "pooler_server_connections"
        ]
        assert check.fatal is False
        assert "UNSET" in check.detail or "not assessed" in check.detail

    def test_it_does_not_scale_with_worker_count(self, preflight):
        """
        The one thing that makes this different from every other budget here: the pooler's
        pool is a property of the DATABASE, not of a process. Four workers do not get four
        pools of 15 — they share the same 15, so adding workers cannot relieve this.
        """
        one = _by_name(preflight.assess(_cfg(WEB_CONCURRENCY=1), users=200))
        four = _by_name(preflight.assess(_cfg(WEB_CONCURRENCY=4), users=200))
        # Same verdict, and the same pool figure quoted — the detail also names the process
        # count, which is worth saying and is not part of the arithmetic.
        assert one["pooler_server_connections"].ok == four["pooler_server_connections"].ok
        for c in (one, four):
            assert "pooler's 40 Postgres connections" in c["pooler_server_connections"].detail
        # And the contrast: the app-pool check DOES scale with workers.
        assert (
            one["db_connections_for_load"].detail
            != four["db_connections_for_load"].detail
        )


class TestItAgreesWithTheHeadroomAnalysis:
    def test_the_load_model_matches(self, preflight, headroom):
        """
        Two tools describing one deployment must not disagree. Both read the same mix and the
        same exchange pacing; a divergence here means one of them is quietly wrong.
        """
        assert preflight.MIX == headroom.MIX
        assert (
            preflight.SECONDS_PER_INTERVIEW_EXCHANGE
            == headroom.SECONDS_PER_INTERVIEW_EXCHANGE
        )

    def test_the_per_slot_output_rate_matches(self, preflight, headroom):
        """
        The OTPM check divides the analysis's measured burst by its slot count. If the report
        shape changes there, this must follow or the tier percentages drift apart.
        """
        assert preflight.REPORT_SECONDS == headroom.REPORT_SECONDS
        assert preflight.REPORT_TOTAL_OUTPUT == headroom.REPORT_TOTAL_OUTPUT
        assert headroom.TIERS["Start"][2] == preflight.START_TIER_OTPM


class TestTheProcessCountIsWhatItMultipliesBy:
    def test_workers_count_the_same_as_replicas(self, preflight):
        """
        A pool belongs to a process, not a container. Four workers on one replica and one
        worker on four replicas are the same fleet, and the preflight must say so.
        """
        a = _by_name(preflight.assess(_cfg(WEB_REPLICA_COUNT=1, WEB_CONCURRENCY=4), users=200))
        b = _by_name(preflight.assess(_cfg(WEB_REPLICA_COUNT=4, WEB_CONCURRENCY=1), users=200))
        assert a["db_connections_for_load"].detail == b["db_connections_for_load"].detail
