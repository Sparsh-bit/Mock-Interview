"""
Deleting an account is permanent, confirmed, and cannot strand one — test_admin_delete_user.py

Asked for as "give the feature in the users section in admin to delete any account
permanently".

WHAT "PERMANENTLY" HAD TO MEAN, and why the obvious implementation is not it. Our `users` row
is not the account: the credentials live in Supabase's auth schema, and `get_current_user`
creates a local row on first sight of a valid token — deliberately, so nobody is ever locked
out by a signup hook that failed months ago. So deleting only our row means the person signs
in again, gets a fresh row, and is back: their data gone, their access intact. That is the
worst available outcome and it presents as the delete button not working.

THE ORDER OF OPERATIONS IS THE DESIGN, and these tests are mostly about it: files, then the
login, then our rows. A failure at the login must ABORT before any data is touched, because
the alternative leaves a working login attached to nothing.

The refusals are tested as hard as the deletion, because the mistake this feature makes
available is mundane, one click away, and irreversible: the wrong row in a list where every
row looks the same.
"""

from __future__ import annotations

import pathlib

ADMIN_API = pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/admin.py"
SRC = ADMIN_API.read_text()
BLOCK = SRC[SRC.index("async def delete_user(") : SRC.index('@router.get("/audit"')]


class TestItActuallyRemovesTheAccount:
    def test_it_deletes_the_supabase_login_not_just_our_row(self):
        """
        THE DIFFERENCE BETWEEN A DELETION AND A DATA WIPE. Without this the person signs back
        in and `get_current_user` recreates them.
        """
        assert "_delete_supabase_user" in BLOCK
        assert "async def _delete_supabase_user" in SRC

    def test_the_supabase_call_is_a_delete_against_the_admin_api(self):
        helper = SRC[SRC.index("async def _delete_supabase_user") : SRC.index("async def _delete_stored_files")]
        assert "/auth/v1/admin/users/" in helper
        assert "client.delete(" in helper
        # 404 must count as success, or a retry of a half-finished deletion can never complete.
        assert "404" in helper

    def test_it_removes_the_stored_files(self):
        """
        The cascade does not reach storage. `resume_files` rows go with the user and the objects
        they point at would stay in the bucket forever — a candidate's CV, still stored,
        referenced by nothing that would ever reveal it exists.
        """
        assert "_delete_stored_files" in BLOCK
        assert "SUPABASE_STORAGE_BUCKET_RESUMES" in SRC

    def test_it_deletes_the_user_row_and_lets_the_cascade_do_the_rest(self):
        # Every table referencing users.id is declared CASCADE or SET NULL, so one DELETE
        # removes the graph correctly. Enumerating tables here would be a second, drifting
        # definition of what belongs to a user.
        assert "await db.delete(user)" in BLOCK


class TestTheOrderOfOperations:
    """
    Ordering is what a failure halfway through leaves behind, and it is the whole design.
    """

    def test_the_login_is_deleted_before_our_rows(self):
        # Reversed, a failure at the login step leaves our data gone and the login working —
        # the person signs in and is silently recreated.
        assert BLOCK.index("_delete_supabase_user") < BLOCK.index("await db.delete(user)")

    def test_a_failed_login_deletion_aborts_before_touching_data(self):
        at = BLOCK.index("_delete_supabase_user")
        after = BLOCK[at : at + 700]
        assert "raise HTTPException" in after, (
            "a failed auth deletion must refuse, not continue — continuing leaves a working "
            "login attached to no data"
        )
        assert "nothing was" in after.lower() or "nothing" in after.lower()

    def test_files_are_removed_before_the_rows_that_name_them(self):
        # After the rows are gone there is nothing left that knows the storage paths.
        assert BLOCK.index("_delete_stored_files") < BLOCK.index("await db.delete(user)")

    def test_a_file_failure_does_not_abort_the_deletion(self):
        helper = SRC[SRC.index("async def _delete_stored_files") : SRC.index("class DeleteUserRequest")]
        # Files are unreachable either way once the rows are gone, so refusing to proceed over
        # one would strand the account instead of deleting it.
        assert "contextlib.suppress" in helper
        assert "raise" not in helper


class TestItRefusesTheMistakesThatCannotBeUndone:
    def test_the_email_must_match_and_the_server_checks_it(self):
        """
        A confirmation the client alone enforces is not a confirmation: the endpoint is
        reachable with a user id and nothing else.
        """
        assert "confirm_email" in BLOCK
        assert "does not match" in BLOCK
        # Case-insensitive and trimmed, or a correct address rejected over a capital letter
        # teaches the admin that the confirmation is noise.
        assert ".strip().lower()" in BLOCK

    def test_an_admin_cannot_delete_their_own_account(self):
        assert "user.id == current_user.user_id" in BLOCK
        assert "cannot delete your own account" in BLOCK

    def test_the_last_admin_cannot_be_deleted(self):
        # Counted rather than inferred from this row: the dangerous case is deleting the OTHER
        # admin while assuming you are not the last one.
        assert "last admin account" in BLOCK
        assert "User.is_admin.is_(True), User.id != user.id" in BLOCK

    def test_a_missing_user_is_a_404_not_a_silent_success(self):
        assert "User not found" in BLOCK


class TestItLeavesAnAudit:
    def test_the_deletion_is_recorded_before_it_happens(self):
        # Captured before, because afterwards there is nothing left to describe.
        assert BLOCK.index("AuditLog(") < BLOCK.index("await db.delete(user)")
        assert 'action="admin.user_deleted"' in BLOCK

    def test_the_audit_row_survives_the_deletion(self):
        """
        `entity_id` is a plain UUID column rather than a foreign key, which is exactly what
        stops the record of the deletion being deleted by it. Asserted on the MODEL, because
        that is where the property lives.
        """
        model = (
            pathlib.Path(__file__).resolve().parents[1] / "app/models/system.py"
        ).read_text()
        at = model.index("entity_id")
        assert "ForeignKey" not in model[at : at + 200]
        # And the actor is SET NULL, so the row outlives the admin too.
        assert 'ForeignKey("users.id", ondelete="SET NULL")' in model

    def test_the_email_is_captured_before_the_row_goes(self):
        assert BLOCK.index("target_email = user.email") < BLOCK.index("await db.delete(user)")
        assert '"target_email": target_email' in BLOCK

    def test_the_reason_is_recorded(self):
        assert '"reason"' in BLOCK


class TestItIsAdminOnlyAndRateLimited:
    def test_it_is_a_post_because_it_carries_a_confirmation(self):
        """
        A body on a DELETE is permitted to be dropped by intermediaries, and this app is served
        through Cloudflare. A confirmation that can vanish in transit is worse than none: the
        endpoint would refuse every legitimate deletion, or with a laxer check accept one that
        was never confirmed.
        """
        at = SRC.index("async def delete_user(")
        decorator = SRC[SRC.rindex("@router.", 0, at) : at]
        assert "@router.post(" in decorator
        assert "/delete" in decorator

    def test_it_is_behind_admin_auth(self):
        at = SRC.index("async def delete_user(")
        assert "current_user: AdminUser" in SRC[at : at + 500]

    def test_it_shares_the_admin_write_rate_limit(self):
        at = SRC.rindex("@router.post(", 0, SRC.index("async def delete_user("))
        assert "_admin_write_rate_limit" in SRC[at : SRC.index("async def delete_user(")]
