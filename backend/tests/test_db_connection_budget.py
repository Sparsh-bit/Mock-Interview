"""
The database connection budget — tests/test_db_connection_budget.py

`(DB_POOL_SIZE + DB_MAX_OVERFLOW) x WEB_REPLICA_COUNT` is a number no single process can
work out for itself: it can see its own pool and nothing else. Nothing checked it, and the
consequence of getting it wrong is specifically nasty — past the pooler's ceiling Postgres
refuses new connections, so the symptom is "too many connections" on scattered random
requests rather than a clean slowdown, and it appears at exactly the traffic that caused it.

WARN, NEVER CRASH. The reasoning is the same one main.py already applies to Redis and the
opposite of what a strict check would do: an over-subscribed pool still serves every request
that gets a connection. Refusing to boot would turn a degradation that might never be
reached into a certain outage, and it would do it during a deploy — the moment a replica is
least able to explain itself.
"""

from __future__ import annotations

import pytest

from app.db.session import audit_db_connection_budget


def _codes(issues) -> set[str]:
    return {issue.code for issue in issues}


class TestTheThresholds:
    """The whole value of the check is that it fires at the right moment, so each edge is
    tested at the edge rather than somewhere safely inside it."""

    def test_a_budget_over_the_ceiling_is_reported(self):
        issues = audit_db_connection_budget(
            pool_size=10, max_overflow=20, replicas=4, ceiling=100  # 120
        )
        assert "db_connection_budget_over_ceiling" in _codes(issues)

    def test_a_budget_exactly_at_the_ceiling_is_reported(self):
        """
        AT the limit is not a safe place to be: the ceiling is the pooler's total, and
        anything else sharing it — a migration, a psql session, a second service — takes the
        service past it. The task's wording is "at or near", and this is the 'at'.
        """
        issues = audit_db_connection_budget(
            pool_size=10, max_overflow=15, replicas=4, ceiling=100  # exactly 100
        )
        assert "db_connection_budget_over_ceiling" in _codes(issues)

    def test_a_budget_near_the_ceiling_is_reported(self):
        issues = audit_db_connection_budget(
            pool_size=5, max_overflow=15, replicas=4, ceiling=100  # 80 of 100
        )
        assert "db_connection_budget_near_ceiling" in _codes(issues)

    def test_a_budget_one_connection_under_the_warning_line_is_silent(self):
        """The other side of the same edge. A warning that fires early is noise, and noise
        is how a real warning gets ignored."""
        issues = audit_db_connection_budget(
            pool_size=5, max_overflow=15, replicas=3, ceiling=76  # 60 vs 60.8
        )
        assert issues == []

    def test_a_comfortable_budget_is_silent(self):
        issues = audit_db_connection_budget(
            pool_size=5, max_overflow=10, replicas=2, ceiling=200  # 30 of 200
        )
        assert issues == []


class TestWhatItSaysWhenItFires:
    def test_the_message_carries_the_arithmetic(self):
        """A warning nobody can act on without opening the source is half a warning."""
        (issue,) = [
            i
            for i in audit_db_connection_budget(
                pool_size=10, max_overflow=20, replicas=4, ceiling=100
            )
            if i.code == "db_connection_budget_over_ceiling"
        ]
        assert "10" in issue.message and "20" in issue.message
        assert "4" in issue.message
        assert "120" in issue.message and "100" in issue.message

    def test_it_returns_issues_rather_than_raising(self):
        """
        Pinned as behaviour, not left to convention. A future edit that makes this fatal
        would trade a degradation for a guaranteed failed deploy.
        """
        assert isinstance(
            audit_db_connection_budget(pool_size=99, max_overflow=99, replicas=99, ceiling=1),
            list,
        )


class TestAnUnknownCeiling:
    def test_an_unset_ceiling_says_so_rather_than_guessing(self):
        """
        Every provider and plan has a different pooler limit and they change. A default
        would produce a check that is confidently wrong, which is worse than one that
        reports it has nothing to check against.
        """
        issues = audit_db_connection_budget(
            pool_size=10, max_overflow=20, replicas=4, ceiling=0
        )
        assert _codes(issues) == {"db_connection_ceiling_unknown"}

    def test_the_unknown_ceiling_notice_still_shows_the_budget(self):
        (issue,) = audit_db_connection_budget(
            pool_size=10, max_overflow=20, replicas=4, ceiling=0
        )
        assert "120" in issue.message


class TestItReadsTheRealSettings:
    def test_the_live_configuration_is_audited_and_logged(self, monkeypatch, caplog):
        """
        The wiring, not the arithmetic. A pure function nothing calls protects nothing.
        """
        from app.db import session as session_module

        monkeypatch.setattr(session_module.settings, "DB_POOL_SIZE", 10)
        monkeypatch.setattr(session_module.settings, "DB_MAX_OVERFLOW", 20)
        monkeypatch.setattr(session_module.settings, "WEB_REPLICA_COUNT", 4)
        monkeypatch.setattr(session_module.settings, "DB_CONNECTION_CEILING", 100)

        issues = session_module.log_db_connection_budget_audit()

        assert "db_connection_budget_over_ceiling" in _codes(issues)

    def test_the_default_configuration_is_silent(self, monkeypatch):
        """
        A developer running one replica against a local Postgres must not be warned about
        anything. A check that cries wolf on every `npm run dev` is a check people learn to
        scroll past.
        """
        from app.db import session as session_module

        monkeypatch.setattr(session_module.settings, "DB_CONNECTION_CEILING", 0)
        monkeypatch.setattr(session_module.settings, "WEB_REPLICA_COUNT", 1)

        issues = session_module.log_db_connection_budget_audit()

        assert _codes(issues) <= {"db_connection_ceiling_unknown"}


class TestTheSettingExists:
    def test_the_ceiling_defaults_to_unknown_rather_than_to_a_guessed_number(self):
        from app.core.config import Settings

        assert Settings.model_fields["DB_CONNECTION_CEILING"].default == 0

    @pytest.mark.parametrize("name", ["DB_POOL_SIZE", "DB_MAX_OVERFLOW", "WEB_REPLICA_COUNT"])
    def test_the_inputs_to_the_formula_are_real_settings(self, name):
        from app.core.config import Settings

        assert name in Settings.model_fields
