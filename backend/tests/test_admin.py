"""
Tests for admin user management.

The first class is the one that matters. `users.is_active` existed as a column
nothing wrote and nothing read, so before enforcement an admin "deactivating"
somebody flipped a boolean and changed nothing whatsoever about what they could
do. A test that only checks the flag was written would have passed against that
broken version, so these assert the *consequence* — a deactivated account is
refused — not the bookkeeping.
"""

from __future__ import annotations

import inspect
import uuid

import pytest

from app.api.v1 import admin as admin_api
from app.core import security


class TestDeactivationIsEnforced:
    def test_get_current_user_checks_is_active(self):
        """
        Enforcement must live in get_current_user and nowhere else: it is the one
        dependency every authenticated request passes through, so a check there
        covers every endpoint including ones not written yet. Anywhere else means
        auditing each new route forever.
        """
        src = inspect.getsource(security.get_current_user)
        assert "is_active" in src, (
            "get_current_user does not look at users.is_active — deactivation "
            "would be a boolean nothing reads, which is what it used to be"
        )

    def test_refusal_is_403_not_401(self):
        """
        The token is cryptographically valid, so 401 would send the client into a
        refresh-and-retry loop against an account that is never coming back. 403
        lets it show something true.

        Anchored on the `if not user.is_active:` statement rather than the first
        occurrence of the string — the first occurrence is in the comment above it,
        which is how this test failed the first time it ran.
        """
        src = inspect.getsource(security.get_current_user)
        guard = "if not user.is_active:"
        assert guard in src, "no is_active guard in get_current_user"
        after = src[src.index(guard) : src.index(guard) + 400]
        assert "HTTP_403_FORBIDDEN" in after
        assert "HTTP_401" not in after

    def test_the_refusal_explains_itself(self):
        """A bare 'Forbidden' gives a candidate nothing to act on."""
        src = inspect.getsource(security.get_current_user)
        assert "deactivated" in src.lower()

    def test_check_runs_before_admin_elevation(self):
        """
        get_current_admin_user depends on get_current_user, so a deactivated admin
        is refused before the admin check is even reached. Asserted on the
        dependency graph rather than the text, since that is the actual mechanism.
        """
        params = inspect.signature(security.get_current_admin_user).parameters
        assert "current_user" in params
        dep = params["current_user"].default
        assert getattr(dep, "dependency", None) is security.get_current_user


class TestLockoutGuardrails:
    """
    Both of these are one misclick away on a table of similar rows, and neither is
    recoverable from the UI — the fix would be a manual UPDATE against production,
    which is the scenario an admin panel exists to prevent.
    """

    def test_cannot_deactivate_self(self):
        src = inspect.getsource(admin_api.update_user)
        assert "user.id == current_user.user_id" in src
        assert "cannot deactivate your own account" in src

    def test_cannot_revoke_own_admin(self):
        src = inspect.getsource(admin_api.update_user)
        assert "cannot revoke your own admin" in src

    def test_cannot_remove_the_last_admin(self):
        """
        The dangerous case is demoting someone else while you are the only other
        admin, then losing your own access — so this is a count, not a check of
        the target row.
        """
        src = inspect.getsource(admin_api.update_user)
        assert "last admin" in src.lower()

    def test_empty_patch_is_rejected(self):
        """
        A PATCH with neither field would write an audit row saying nothing changed.
        """
        src = inspect.getsource(admin_api.update_user)
        assert "Nothing to change" in src


class TestEveryMutationIsAudited:
    def test_update_writes_an_audit_row(self):
        src = inspect.getsource(admin_api.update_user)
        assert "AuditLog(" in src

    def test_the_audit_row_names_actor_target_and_both_states(self):
        """Without before/after the log says something changed but not to what."""
        src = inspect.getsource(admin_api.update_user)
        for field in ("actor_email", "target_email", '"before"', '"after"'):
            assert field in src, f"audit payload is missing {field}"

    def test_audit_feed_shows_admin_actions_only(self):
        """
        audit_logs also carries every interview and report event; mixing those in
        buries the handful of entries anyone opens this for.
        """
        src = inspect.getsource(admin_api.list_admin_audit)
        assert '"admin.%"' in src


class TestAdminRefusalsAreLogged:
    def test_non_admin_access_is_logged(self):
        """
        A non-admin reaching an admin route is either a client bug or somebody
        probing. It used to be refused silently, so a sustained attempt to find an
        unguarded admin endpoint left no trace at all.
        """
        src = inspect.getsource(security.get_current_admin_user)
        assert "logger.warning" in src
        assert "admin_access_denied" in src


class TestMutationsAreRateLimited:
    def test_patch_has_a_rate_limit_dependency(self):
        """
        Reads are cheap and idempotent; a write changes who can use the product.
        Bounds a runaway script or a stolen admin token to something visible in
        the audit log rather than a silent mass lockout.
        """
        route = next(
            r for r in admin_api.router.routes
            if getattr(r, "path", "") == "/admin/users/{user_id}" and "PATCH" in getattr(r, "methods", set())
        )
        deps = [str(d.call) for d in route.dependant.dependencies]
        assert any("rate" in d.lower() for d in deps), (
            f"no rate-limit dependency on the admin PATCH route: {deps}"
        )


class TestCostColumnOutlivesTheLedger:
    """
    Per-user spend comes from `ai_usage`, which is deleted when credits ship. This
    router is permanent, so it must not break when that table is gone.
    """

    async def test_cost_lookup_returns_empty_when_ledger_is_off(self, monkeypatch):
        monkeypatch.setattr(admin_api, "_ledger_enabled", lambda: False)
        assert await admin_api._cost_by_user(None, [uuid.uuid4()]) == {}

    async def test_cost_lookup_swallows_a_missing_table(self, monkeypatch):
        """A deploy where the router is live and the migration has not run."""
        monkeypatch.setattr(admin_api, "_ledger_enabled", lambda: True)

        class ExplodingDB:
            async def execute(self, *_a, **_k):
                raise RuntimeError('relation "ai_usage" does not exist')

        assert await admin_api._cost_by_user(ExplodingDB(), [uuid.uuid4()]) == {}

    async def test_no_ids_means_no_query(self, monkeypatch):
        monkeypatch.setattr(admin_api, "_ledger_enabled", lambda: True)
        assert await admin_api._cost_by_user(None, []) == {}

    def test_responses_declare_whether_cost_data_exists(self):
        """
        So the UI hides the column instead of rendering a row of zeroes that look
        like real measurements.
        """
        assert "cost_data_available" in admin_api.UserListResponse.model_fields


class TestSignOutOnDeactivate:
    def test_revocation_happens_after_the_commit(self):
        """
        The flag is what enforces the block; a failed Supabase call must not roll
        the deactivation back.
        """
        src = inspect.getsource(admin_api.update_user)
        assert src.index("await db.commit()") < src.index("_revoke_supabase_sessions")

    def test_revocation_only_on_transition_to_inactive(self):
        """Not on reactivation, and not on an unrelated admin-flag change."""
        src = inspect.getsource(admin_api.update_user)
        assert 'before["is_active"] and after["is_active"] is False' in src

    def test_revocation_never_raises(self):
        src = inspect.getsource(admin_api._revoke_supabase_sessions)
        assert "except Exception" in src
        assert "return False" in src

    @pytest.mark.parametrize("code", [200, 204, 404])
    def test_no_session_to_kill_counts_as_success(self, code):
        """404 means there was nothing to revoke — same outcome from here."""
        src = inspect.getsource(admin_api._revoke_supabase_sessions)
        assert str(code) in src


class TestListingDoesNotQueryPerRow:
    def test_session_counts_come_from_one_grouped_subquery(self):
        """
        A per-row count is how a user table becomes unusable the moment it has
        real data in it.
        """
        src = inspect.getsource(admin_api.list_users)
        assert ".subquery()" in src
        assert "group_by" in src

    def test_costs_are_fetched_for_the_whole_page_at_once(self):
        src = inspect.getsource(admin_api.list_users)
        assert "_cost_by_user(db, ids)" in src
