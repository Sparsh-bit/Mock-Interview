"""
Every interview charge names the session it paid for — tests/test_charge_is_attributable.py

REPORTED: "the report has been shown without payment i created a new account given the free
interview and it showed the report without any payment".

THE HOLE WAS NOT IN THE PAYWALL. `report_access` was working exactly as written: it decides by
finding the consume row for a session, and it FAILS OPEN when it cannot find one, because
locking a report somebody already owns is far worse than failing to charge for one. That design
is right and is not what changed.

The hole was that `/interview/plan` charged with `session_id=None`. It charges BEFORE
generating — deliberately, so an exhausted user does not pay for the expensive part before
being refused — and the session does not exist until `create_plan` returns. So the ledger held
a charge attached to nothing, which is indistinguishable from no charge at all, and every
interview begun through that endpoint produced a free report. That is most of them.

WHY THIS FILE GUARDS THE CLASS AND NOT THE INSTANCE. The same mistake is available to every
future endpoint that begins an interview: charge, generate, forget to attach. The instance is
one line; the class is "an unattributable charge silently gives away the thing it paid for",
and it is silent in both directions — nothing errors, and the candidate is not billed twice.
So the test is over the CALL SITES, not over one of them.
"""

from __future__ import annotations

import pathlib
import re

INTERVIEW_API = pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/interview.py"


class TestEveryChargeCanBeTracedToItsSession:
    """
    Source-level, because the failure is an ABSENCE — a keyword argument nobody passed — and an
    absence in a path that is otherwise correct cannot be reached from outside without standing
    up a live interview and a live AI call.
    """

    def test_every_interview_charge_names_a_session(self):
        src = INTERVIEW_API.read_text()
        calls = list(
            re.finditer(r'consume\(\s*db,\s*current_user\.user_id,\s*"interview"', src)
        )
        assert calls, "the interview charge moved; this guard needs repointing"

        for match in calls:
            # The call's own argument list, up to its closing paren.
            tail = src[match.start() : src.index(")", match.start()) + 1]
            if "session_id=" in tail:
                continue
            # Otherwise the charge MUST be captured and attached after the session exists.
            # Anything else is the bug: a row in the ledger that names no session.
            head = src[: match.start()].rsplit("\n", 1)[-1]
            assert "=" in head, (
                "an interview charge neither passes session_id nor keeps the returned row to "
                "attach one. An unattributable charge reads as no charge to report_access, "
                "which fails open and gives the report away."
            )
            after = src[match.end() :]
            assert ".session_id =" in after, (
                "the charge is captured but never attached to a session — see the module "
                "docstring for why that gives away paid reports."
            )

    def test_the_charge_and_the_attachment_are_in_one_transaction(self):
        # `get_db` owns the commit. If the attachment were committed separately, a failure
        # between them would leave a charge that still names no session — the same bug with a
        # smaller window.
        src = INTERVIEW_API.read_text()
        start = src.index("async def plan_interview")
        # Bounded to THIS function. Slicing to the end of the file swept in other endpoints
        # that legitimately commit, which made the assertion fail for the wrong reason — the
        # first version of this test reported a bug in code it was not looking at.
        end = src.index("\nasync def ", start + 1)
        plan_block = src[start:end]
        assert "db.commit()" not in plan_block, (
            "committing inside the endpoint breaks the atomicity the charge relies on"
        )

    def test_consume_returns_the_row_so_it_can_be_attached(self):
        import inspect

        from app.services.billing import credits

        sig = inspect.signature(credits.consume)
        assert sig.return_annotation != "None", (
            "consume returning None again removes the only way a charge-before-generate call "
            "site can attach its session"
        )


# ─── The report-locking half of this file has been removed ────────────────────────────────
#
# It asserted that a trial-paid interview's report came back LOCKED and a purchased one did
# not. Interviews are paid outright now, so there is no free interview whose report could be
# charged for, and the paywall was removed with the pricing change.
#
# WHAT REMAINS ABOVE IS STILL THE POINT, and is if anything more important without the
# paywall: an interview charge that names no session is an unattributable charge, and the
# ledger is the only record of who was charged for what. It answers a refund question, an
# "I was billed twice" question, and the admin marketing view's per-session columns. A charge
# that cannot be tied to the thing it paid for makes all three unanswerable.
