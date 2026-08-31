"""
The fleet arithmetic when a replica holds more than one process.

WHY THIS FILE EXISTS. Every connection budget in core/config.py is PER PROCESS, and until
`WEB_CONCURRENCY` was declared the audits multiplied by `WEB_REPLICA_COUNT` alone. That was
correct only by accident: the Dockerfile started exactly one uvicorn worker, so replicas and
processes were the same number. They stop being the same number the moment anyone sets
`WEB_CONCURRENCY` to use more than one core — and the audits would then have reported a
fraction of the real fleet while saying nothing was wrong, which is the one failure mode this
codebase consistently refuses to accept.

Two things are pinned here, and both are the wiring rather than the arithmetic:

  1. PROCESS_COUNT multiplies BOTH factors.
  2. The database and Redis audits read PROCESS_COUNT, not either factor alone.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings, settings

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestTheProcessCountIsBothFactors:
    def test_it_multiplies_replicas_by_workers(self):
        s = Settings.model_construct(WEB_REPLICA_COUNT=2, WEB_CONCURRENCY=4)
        assert s.PROCESS_COUNT == 8

    def test_one_worker_on_one_replica_is_one_process(self):
        """
        The default has to be the truth for the single-process case, or the audits start
        warning on every `npm run dev`.
        """
        assert Settings.model_fields["WEB_REPLICA_COUNT"].default == 1
        assert Settings.model_fields["WEB_CONCURRENCY"].default == 1
        assert settings.PROCESS_COUNT == 1

    def test_workers_alone_still_multiply(self):
        """
        The case the old arithmetic got wrong: one container, four workers. Four pools, and
        WEB_REPLICA_COUNT is still 1.
        """
        s = Settings.model_construct(WEB_REPLICA_COUNT=1, WEB_CONCURRENCY=4)
        assert s.PROCESS_COUNT == 4


class TestBothAuditsReadIt:
    """
    The audits are what make an over-subscribed pool visible at boot. Reading either factor
    on its own makes them wrong in the OPTIMISTIC direction — the failure where nothing warns.
    """

    def test_the_database_audit_multiplies_by_the_process_count(self, monkeypatch):
        from app.db import session as session_module

        monkeypatch.setattr(session_module.settings, "DB_POOL_SIZE", 5)
        monkeypatch.setattr(session_module.settings, "DB_MAX_OVERFLOW", 10)
        monkeypatch.setattr(session_module.settings, "WEB_REPLICA_COUNT", 1)
        monkeypatch.setattr(session_module.settings, "WEB_CONCURRENCY", 8)
        monkeypatch.setattr(session_module.settings, "DB_CONNECTION_CEILING", 100)

        issues = session_module.log_db_connection_budget_audit()

        # (5 + 10) x 8 processes = 120, past a ceiling of 100. One replica, so an audit
        # reading WEB_REPLICA_COUNT alone would see 15 and stay silent.
        codes = {i.code for i in issues}
        assert "db_connection_budget_over_ceiling" in codes
        assert any("120" in i.message for i in issues)

    def test_the_redis_audit_multiplies_by_the_process_count(self, monkeypatch):
        from app.db import redis as redis_module

        # A MANAGED, TLS URL. The audit deliberately skips the budget check for a local
        # Redis — a developer on localhost has no provider ceiling to breach — so a default
        # URL here would make this test pass for the wrong reason.
        monkeypatch.setattr(
            redis_module.settings, "REDIS_URL", "rediss://default:x@fake.upstash.io:6379"
        )
        monkeypatch.setattr(redis_module.settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(redis_module.settings, "REDIS_MAX_CONNECTIONS", 20)
        monkeypatch.setattr(redis_module.settings, "WEB_REPLICA_COUNT", 1)
        monkeypatch.setattr(redis_module.settings, "WEB_CONCURRENCY", 8)
        monkeypatch.setattr(redis_module.settings, "REDIS_CONNECTION_CEILING", 100)

        issues = redis_module.log_redis_configuration_audit()

        # 20 x 8 processes = 160 against a ceiling of 100. One replica, so an audit reading
        # WEB_REPLICA_COUNT alone would see 20 and stay silent.
        codes = {i.code for i in issues}
        assert "redis_pool_budget_over_ceiling" in codes, codes
        assert any("160" in i.message for i in issues)

    def test_neither_audit_reads_the_replica_count_directly_any_more(self):
        """
        A source guard, because the regression is silent: swapping PROCESS_COUNT back for
        WEB_REPLICA_COUNT breaks no test that runs one worker, and only shows up as a
        connection ceiling breached in production.
        """
        for path in ("backend/app/db/session.py", "backend/app/db/redis.py"):
            source = (REPO_ROOT / path).read_text()
            assert "replicas=settings.PROCESS_COUNT" in source, path
            assert "replicas=settings.WEB_REPLICA_COUNT" not in source, path


class TestNothingHoldsATransactionAcrossAModelCall:
    """
    THE TIGHTEST CEILING IN THE SYSTEM, GUARDED AT ITS THREE SITES.

    Behind a transaction-mode pooler, an idle connection costs no Postgres backend but an OPEN
    TRANSACTION occupies one of the pooler's — 15 on a Supabase Nano, shared by every process.
    Unlike every other budget here it does NOT divide by the worker count: four workers share
    the same 15, so no amount of compute relieves it. The only levers are raising the pool size
    and holding transactions for less time.

    Three code paths used to hold one across a model call. Each is a source guard rather than a
    load test, because under load the regression is invisible until the pooler queue forms —
    and that queue is inside the pooler, where nothing in this application can log it.
    """

    def test_the_cross_question_path_commits_before_generating(self):
        source = (REPO_ROOT / "backend/app/services/interview/orchestrator.py").read_text()
        call = "cross = await self._generate_cross_question("
        assert source.count(call) == 1
        before = source[: source.index(call)]
        # The commit must be the last database statement before the generation.
        tail = before[-2500:]
        assert "await self.db.commit()" in tail, (
            "get_next_question holds a pooled transaction across an 18s model call — commit "
            "after the reads, as reports.py and panel.py do"
        )

    def test_the_avoid_list_is_built_before_the_release_not_after(self):
        """
        The reads have to finish first or the commit relocates the problem instead of fixing
        it: a query after the release re-acquires a connection and holds it across the call.
        """
        source = (REPO_ROOT / "backend/app/services/interview/orchestrator.py").read_text()
        start = source.index("last_q = await self.db.get(Question, last_answer.question_id)")
        end = source.index("cross = await self._generate_cross_question(")
        window = source[start:end]
        assert "_cross_question_avoid_list" in window
        assert window.index("_cross_question_avoid_list") < window.index("await self.db.commit()")

    def test_the_pooler_pool_size_is_configurable_and_undefaulted(self):
        """
        No guessed ceiling, same rule as DB_CONNECTION_CEILING and REDIS_CONNECTION_CEILING:
        it varies by compute size, so 0 means "nobody has read it off the dashboard".
        """
        assert Settings.model_fields["DB_POOLER_POOL_SIZE"].default == 0


class TestTheServerObeysTheSameVariable:
    def test_nothing_hardcodes_a_worker_count_past_the_env_var(self):
        """
        Uvicorn defaults `--workers` to $WEB_CONCURRENCY, which is why the application reads
        that exact name: one variable, obeyed by both the server and the audits, so they
        cannot disagree. A `--workers N` literal in the Dockerfile would break that — the
        server would start N processes and the audits would never hear about it.
        """
        dockerfile = (REPO_ROOT / "Dockerfile").read_text()
        assert not re.search(r"--workers[ =]\d+", dockerfile), (
            "Dockerfile pins a worker count as a literal. Set WEB_CONCURRENCY instead, which "
            "uvicorn already reads and which PROCESS_COUNT multiplies into both audits."
        )


class TestThePanelReleasesItsConnectionBeforeTheModelCall:
    """
    A GD round is a turn every 18s per candidate, and a turn's model call is ~12s. Holding a
    pooled connection across it means 50 candidates in rounds need ~34 connections from a
    30-connection pool — and past the pool EVERY endpoint blocks for DB_POOL_TIMEOUT.

    A source guard rather than a load test, because that is the smallest thing that fails when
    the commit is removed. Under load the regression is invisible until the pool is gone.
    """

    def test_both_turn_endpoints_commit_between_the_context_and_the_generation(self):
        source = (REPO_ROOT / "backend/app/api/v1/panel.py").read_text()

        call = "turn_ctx = await _turn_context(db, request, current_user.user_id)"
        assert source.count(call) == 2, "expected the whole-turn and streaming endpoints"

        for start in (m.end() for m in re.finditer(re.escape(call), source)):
            # The commit must be the next database statement after the context is built.
            window = source[start : start + 2000]
            assert "await db.commit()" in window, (
                "a panel turn holds its pooled connection across the model call — commit "
                "after _turn_context, as reports.py does"
            )

    def test_nothing_touches_the_session_after_the_release(self):
        """
        Committing is only safe because the rest of the turn is Redis and plain strings. A new
        `db.` call after the release would re-acquire a connection and hold it right back
        across the stream, which is the thing this is meant to stop.
        """
        source = (REPO_ROOT / "backend/app/api/v1/panel.py").read_text()
        last_context = source.rindex("turn_ctx = await _turn_context(")
        after = source[last_context:]
        stray = [
            line.strip()
            for line in after.splitlines()
            if re.search(r"\bawait db\.(?!commit\b)\w+", line) and not line.strip().startswith("#")
        ]
        assert not stray, f"database use after the connection was released: {stray}"
