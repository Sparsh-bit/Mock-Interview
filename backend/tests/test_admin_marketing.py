"""
The marketing list — tests/test_admin_marketing.py

"i want the activity and what is left in each user id as the information for me to mail them
for marketing."

THE ONE TEST IN HERE THAT MUST NEVER BE DELETED is `test_remaining_matches_credits_exactly`.
The "what is left" column is a number that gets QUOTED AT A CUSTOMER in an email — "you still
have a free interview waiting" — and it is computed by a set-wide query in `admin.py` rather
than by `credits.remaining_for`, because calling that per row is the N+1 that turns this page
into a timeout. Two implementations of one arithmetic is exactly the situation this repo's
billing notes warn about: a second number that can disagree with the first. Nothing about the
two functions looking similar keeps them equal, so this file runs BOTH against the same real
ledger rows and asserts they agree for every user and every feature, including the awkward
cases — no ledger at all, over-consumption that must clamp at zero, and a purchase on top.

THE SECOND THING IT PINS IS THE QUERY COUNT. Per-user balances across every account is the
textbook place for a loop of queries, and it fails gracefully in the worst way: the page just
gets slower as the product succeeds, which reads as "the admin page is sluggish lately"
rather than as a bug with a cause. `TestTheAggregatesAreNotPerRow` counts the statements the
endpoint issues and asserts the count does not move between one account and five.

THE THIRD IS DISCLOSURE. This endpoint returns every candidate's email address in one
response, and it is one convenient field away from also returning what they said in an
interview. `TestNoNewDisclosure` pins the exact key set of a row, so widening it has to be a
deliberate act with a test change attached.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.api.v1 import admin as admin_api
from app.api.v1.admin import (
    _MARKETING_MAX_ROWS,
    _SEGMENTS,
    MarketingRow,
    _activity_by_user,
    _latest,
    _remaining_by_user,
    _segment_of,
)
from app.services.billing.credits import KIND_CONSUME, KIND_GRANT, KIND_PURCHASE
from app.services.billing.plans import FEATURES, trial_allowance

# `asyncio_mode = "auto"` in pyproject.toml, so the async tests below need no marker — and
# adding one here would put an asyncio mark on the synchronous half of this file, which
# pytest-asyncio warns about once per test.


# ── Segmentation, which needs no database ────────────────────────────────────


class TestSegmentPrecedence:
    """
    Every account gets exactly one segment, and which one is a product decision.

    The column exists to answer "which of my five emails does this person get", so a row that
    could match two segments would hand the tie back to the person doing the mailing — which
    is the work the column was added to remove. These tests are the precedence table written
    out: paid outranks everything, then a waiting report, then a finished session with no
    report, then an abandoned attempt, then nothing at all.
    """

    def test_a_payer_is_a_customer_whatever_else_is_true(self):
        # The important direction: somebody who has paid AND has an unpaid-looking report is
        # still a customer. Getting this backwards sends an offer to somebody who just bought,
        # which is the single most annoying email a product can send.
        assert _segment_of(True, reports=1, completed=1, started=1, answers=3) == "customer"
        assert _segment_of(True, reports=0, completed=0, started=0, answers=0) == "customer"

    def test_a_report_with_no_payment_is_the_money_segment(self):
        # The drive paywall's whole audience: the interview is sat, the report is generated
        # and stored, and one ₹50 unlock stands between them and reading it.
        assert _segment_of(False, reports=1, completed=1, started=1, answers=3) == "report_waiting"

    def test_finishing_without_a_report_is_not_a_sales_email(self):
        # Something did not complete. Asking this person for money for a report they cannot
        # see would be asking them to pay for our bug.
        assert _segment_of(False, reports=0, completed=1, started=1, answers=3) == "finished_no_report"

    def test_starting_and_not_finishing_is_its_own_group(self):
        # SPLIT INTO TWO, and this is the distinction the screen was hiding. Both used to be
        # `dropped_off`, which was the largest group on it: somebody who closed the tab while
        # their first question was still being written has had a completely different
        # experience from somebody who answered eight and stopped, and they need opposite
        # emails — an apology versus a nudge.
        assert (
            _segment_of(False, reports=0, completed=0, started=2, answers=4) == "stopped_partway"
        )
        assert (
            _segment_of(False, reports=0, completed=0, started=2, answers=0)
            == "left_before_answering"
        )

    def test_doing_nothing_at_all_is_its_own_group(self):
        # Still holding their whole free trial, so the email is "your free interview is still
        # here" and must never contain a price.
        assert _segment_of(False, reports=0, completed=0, started=0, answers=0) == "never_started"

    def test_every_possible_row_lands_in_exactly_one_known_segment(self):
        """
        Exhaustive over the shape of the input, because a row with no segment would render as
        a blank cell in a mail-merge column and get mailed the wrong thing or nothing at all.
        """
        known = {seg for seg, _label, _happened, _pitch in _SEGMENTS}
        for paid in (False, True):
            for reports in range(3):
                for completed in range(3):
                    for started in range(3):
                        for answers in (0, 5):
                            assert _segment_of(paid, reports, completed, started, answers) in known

    def test_every_segment_carries_the_reason_it_is_being_mailed(self):
        # A segment whose purpose has been forgotten is a segment that quietly starts
        # receiving the wrong email, so the pitch lives beside the rule and is not optional.
        for seg, label, happened, pitch in _SEGMENTS:
            assert seg and label and pitch
            assert len(pitch) > 20, f"{seg} has no real pitch"
            # WHAT HAPPENED IS NOW PART OF THE CONTRACT. The screen used to render the raw key
            # — `dropped_off` — which says nothing to the person writing the email. Every
            # segment has to describe the account in plain words, and the label must not just
            # be the key with the underscores taken out.
            assert len(happened) > 30, f"{seg} does not say what actually happened"
            assert seg.replace("_", " ") != label.lower(), f"{seg}'s label is just its key"


class TestLatestTimestamp:
    """
    "Last active" is the newest of three tables' timestamps, any of which can be absent.

    `max()` over an empty sequence raises, and the row it would raise on is the commonest one
    in a marketing list — an account that signed up and did nothing.
    """

    def test_nothing_known_is_none_rather_than_an_error(self):
        assert _latest(None, None, None) is None

    def test_the_newest_wins(self):
        old = datetime(2026, 1, 1, tzinfo=UTC)
        new = datetime(2026, 8, 1, tzinfo=UTC)
        assert _latest(old, new, None) == new
        assert _latest(None, old, new) == new


# ── Disclosure boundary ──────────────────────────────────────────────────────


class TestNoNewDisclosure:
    """
    This endpoint must not become a new way to read anything the admin screen does not
    already show.

    It returns every candidate's email in one response. That is the same personal data
    `GET /admin/users` already lists, plus counts and flags — and it is one convenient field
    away from also carrying what somebody said in an interview.
    """

    def test_the_row_is_exactly_these_fields(self):
        # Pinned as an exact set rather than a "does not contain" check: a deny-list only
        # catches the leaks somebody thought of, and this is a list of students' data.
        assert set(MarketingRow.model_fields) == {
            "user_id",
            "email",
            "full_name",
            "joined_at",
            "is_active",
            "is_admin",
            "unlimited",
            "remaining",
            "sessions_started",
            "sessions_completed",
            "reports",
            "last_active_at",
            "ever_paid",
            "last_paid_at",
            # ADDED DELIBERATELY. This set is pinned so that widening what a mailing list
            # carries is a decision somebody makes, not something that happens.
            #
            # `purchases` is a COUNT, never a rupee total: /admin/revenue is the single
            # reconciling money figure and has to dedupe double-grants, so a second per-user
            # total here would be a number that disagrees with it beside a person's name.
            #
            # `best_score` is the one interview-DERIVED value on the row, and the boundary is
            # the point: a score is a figure about an account; questions, answers and
            # transcripts are the candidate's own words and stay out. The grep test below is
            # what keeps that line where it is.
            "purchases",
            "scored_reports",
            "best_score",
            # ADDED DELIBERATELY. What the account thinks of US, which is the one thing on
            # this row that is the candidate's opinion rather than a measurement of them.
            # `ratings_given` is beside it because a single one-star from somebody who sat one
            # interview means something different from a one-star average across five.
            "avg_stars",
            "ratings_given",
            "segment",
        }

    def test_no_interview_content_is_reachable_through_it(self):
        """
        Counts and flags, never content. Asserted on the source because the risk is a future
        edit that adds "and the last thing they said" for context.
        """
        src = inspect.getsource(admin_api.marketing_list)
        for forbidden in ("Answer", "Score", "raw_report", "executive_summary", "transcript"):
            assert forbidden not in src, f"marketing_list reaches {forbidden}"

    def test_it_is_gated_by_the_same_admin_dependency_as_every_other_route_here(self):
        """
        `AdminUser`, not a hand-rolled check. That annotation resolves to
        `get_current_admin_user`, which depends on `get_current_user`, which is where
        `is_active` is enforced — so a deactivated admin is refused before the admin check is
        even reached. Compared against the endpoint next to it so this cannot pass by
        matching a string that means nothing.
        """
        from app.core.security import AdminUser, get_current_admin_user

        # `from __future__ import annotations` leaves these as strings, so the annotation is
        # compared by name and the name is then proved to mean what it should — the string
        # alone would pass against an `AdminUser` that had been quietly redefined.
        for endpoint in (admin_api.marketing_list, admin_api.list_users):
            assert (
                inspect.signature(endpoint).parameters["current_user"].annotation == "AdminUser"
            )
        assert AdminUser.__metadata__[0].dependency is get_current_admin_user

    def test_pulling_the_whole_user_base_is_rate_limited(self):
        """
        Not about cost — five grouped aggregates are cheap. It is that this is the only
        endpoint that returns every email address in the product, so an admin token in a loop
        should trip something.
        """
        src = inspect.getsource(admin_api)
        assert "_marketing_read_rate_limit" in src
        assert "rate_limit_admin(user_id)}:marketing" in src, (
            "the marketing read shares the admin mutation bucket — an export loop could then "
            "eat the budget the deactivate button needs during an incident"
        )


class TestTheListIsBounded:
    def test_the_cap_is_a_response_bound_and_says_so_when_it_bites(self):
        # Unpaginated on purpose: the export has to be the whole list, and a "download" that
        # silently covered page one only would be worse than no export at all. So the cap has
        # to announce itself rather than quietly shortening the list.
        assert _MARKETING_MAX_ROWS >= 1000
        src = inspect.getsource(admin_api.marketing_list)
        assert "truncated=total > len(users)" in src


class TestTheAggregatesAreNotPerRow:
    """
    Structural half of the N+1 guard. The counting half is in `TestQueryCount` below, which
    needs a database; this half fails fast and needs nothing.
    """

    def test_balances_are_one_grouped_query_for_the_whole_list(self):
        src = inspect.getsource(_remaining_by_user)
        assert "user_id.in_(user_ids)" in src
        assert "group_by" in src
        # The N+1 that would be easiest to write and hardest to notice. Matched on the call
        # rather than on the name, because the docstring names `remaining_for` deliberately —
        # explaining which function this is the set-wide form of is the point of it.
        assert "await remaining_for" not in src and "remaining_for(db" not in src, (
            "calling credits.remaining_for per user is the loop this function exists to avoid"
        )

    def test_activity_is_a_fixed_number_of_grouped_queries(self):
        src = inspect.getsource(_activity_by_user)
        assert src.count("group_by") == 5, (
            "one aggregate per table: sessions, answers, reports, feedback, ledger"
        )
        # Five executes for five aggregates. The number may grow when a table is added; what
        # must never change is that it is a CONSTANT — the test below proves it does not grow
        # with the number of accounts, which is the property that actually matters.
        assert src.count("await db.execute") == 5


# ── Against a real database ──────────────────────────────────────────────────


class _CountingSession:
    """
    A pass-through around the real session that counts statements.

    Wrapping rather than monkey-patching the AsyncSession: the endpoint only ever calls
    `execute`, and a proxy cannot be defeated by SQLAlchemy caching or by attribute slots.
    """

    def __init__(self, db) -> None:
        self._db = db
        self.executions = 0

    async def execute(self, *a, **kw):
        self.executions += 1
        return await self._db.execute(*a, **kw)

    def __getattr__(self, name):
        return getattr(self._db, name)


class _FakeAdmin:
    """Only `user_id` and `email` are read by the endpoint."""

    def __init__(self) -> None:
        self.user_id = uuid.uuid4()
        self.email = "admin@example.test"


@pytest.fixture
async def population():
    """
    Five accounts, one per segment, plus the ledger and sessions that put them there.

    REAL ROWS THROUGH REAL FOREIGN KEYS. `credit_events.user_id`, `interview_sessions.track_id`
    and `reports.session_id` are all enforced, so the fixture builds the whole chain
    (company → track → session → report) rather than inventing ids. A fixture that diverges
    from the schema tests something the app cannot produce.

    The schema is created here because `test_integration.py` drops it, so a test that assumes
    one is order-dependent — and would SKIP rather than fail, which is worse than either.
    """
    from sqlalchemy import delete
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import AsyncSessionFactory, engine
    from app.models.base import Base
    from app.models.billing import CreditEvent, UserPlan
    from app.models.company import Company, InterviewTrack
    from app.models.report import Report
    from app.models.session import InterviewSession, SessionStatus
    from app.models.user import User

    ids = {
        k: uuid.uuid4()
        for k in ("fresh", "dropper", "waiting", "payer", "overdrawn", "unscored", "buyer")
    }
    company_id, track_id = uuid.uuid4(), uuid.uuid4()
    session_ids = {
        k: uuid.uuid4() for k in ("dropper_a", "dropper_b", "waiting", "payer", "unscored")
    }
    now = datetime.now(UTC)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with AsyncSessionFactory() as db:
            for key, uid in ids.items():
                db.add(
                    User(
                        id=uid,
                        supabase_uid=str(uid),
                        email=f"mkt-{key}-{uid.hex[:6]}@example.test",
                        is_active=True,
                        is_admin=False,
                    )
                )
            db.add(Company(id=company_id, name="Mkt Co", slug=f"mkt-{uuid.uuid4().hex[:8]}"))
            db.add(
                InterviewTrack(
                    id=track_id,
                    company_id=company_id,
                    name="Mkt Track",
                    slug=f"mkt-{uuid.uuid4().hex[:8]}",
                )
            )
            await db.flush()

            def session_row(sid, uid, status, created):
                return InterviewSession(
                    id=sid,
                    user_id=uid,
                    track_id=track_id,
                    status=status,
                    mode="text",
                    created_at=created,
                )

            def report_row(sid, uid, created):
                return Report(
                    id=uuid.uuid4(),
                    session_id=sid,
                    user_id=uid,
                    overall_score=71.5,
                    overall_score_label="Good",
                    executive_summary="Solid on collections, thin on Spring.",
                    readiness_level="close_to_ready",
                )

            def event(uid, feature, kind, delta, created, **kw):
                return CreditEvent(
                    id=uuid.uuid4(),
                    user_id=uid,
                    feature=feature,
                    kind=kind,
                    delta=delta,
                    created_at=created,
                    **kw,
                )

            # `fresh` gets nothing at all: no plan row, no ledger, no session. The commonest
            # row in a real marketing list, and the one every aggregate has to survive.

            # `dropper`: two starts, nothing finished, one interview spent.
            db.add(session_row(session_ids["dropper_a"], ids["dropper"], SessionStatus.ABANDONED,
                               now - timedelta(days=3)))
            db.add(session_row(session_ids["dropper_b"], ids["dropper"], SessionStatus.ACTIVE,
                               now - timedelta(days=2)))
            db.add(event(ids["dropper"], "interview", KIND_CONSUME, -1, now - timedelta(days=3)))

            # `waiting`: finished, and the report is SCORED. Was described here as "the ₹50
            # audience" — a report unlock that no longer exists at any price; reports come
            # with the interview now.
            db.add(session_row(session_ids["waiting"], ids["waiting"], SessionStatus.COMPLETED,
                               now - timedelta(days=1)))
            db.add(report_row(session_ids["waiting"], ids["waiting"], now - timedelta(days=1)))
            db.add(event(ids["waiting"], "interview", KIND_CONSUME, -1, now - timedelta(days=1)))

            # `unscored`: finished, a report row exists, and it was NEVER SCORED — the
            # placeholder written when generation fails. This is what `report_waiting` means
            # now, and it is a genuinely different email from the scored case: their answers
            # are safe and the report completes itself on the next open, so there is nothing
            # to sell them and something to reassure them about.
            db.add(session_row(session_ids["unscored"], ids["unscored"], SessionStatus.COMPLETED,
                               now - timedelta(days=2)))
            db.add(
                Report(
                    id=uuid.uuid4(),
                    session_id=session_ids["unscored"],
                    user_id=ids["unscored"],
                    overall_score=0.0,
                    overall_score_label="Pending",
                    executive_summary="Scoring did not finish.",
                    readiness_level="needs_more_practice",
                )
            )
            db.add(event(ids["unscored"], "interview", KIND_CONSUME, -1, now - timedelta(days=2)))

            # `buyer`: paid and has never practised. The `customer` segment, which a scored
            # report now outranks — so this is the account that keeps it reachable.
            db.add(
                event(
                    ids["buyer"], "interview", KIND_PURCHASE, 5, now - timedelta(hours=3),
                )
            )

            # `payer`: finished, report exists, bought a five-pack.
            db.add(session_row(session_ids["payer"], ids["payer"], SessionStatus.COMPLETED,
                               now - timedelta(days=5)))
            db.add(report_row(session_ids["payer"], ids["payer"], now - timedelta(days=5)))
            db.add(event(ids["payer"], "interview", KIND_CONSUME, -1, now - timedelta(days=5)))
            db.add(
                event(
                    ids["payer"], "interview", KIND_PURCHASE, 5, now - timedelta(hours=2),
                    payment_ref=f"pay_mkt{uuid.uuid4().hex[:10]}",
                    detail={"item_id": "interview_5", "amount_paise": 19900},
                )
            )

            # `overdrawn`: more consumption than allowance, and a 100%-off GRANT rather than a
            # purchase. Two separate traps — the balance must clamp at zero rather than going
            # negative, and free product must not make somebody look like a paying customer.
            for i in range(3):
                db.add(event(ids["overdrawn"], "gd", KIND_CONSUME, -1, now - timedelta(days=9 + i)))
            db.add(event(ids["overdrawn"], "gd", KIND_GRANT, 1, now - timedelta(days=8)))

            await db.commit()
            yield db, ids

            await db.execute(delete(Report).where(Report.user_id.in_(list(ids.values()))))
            await db.execute(
                delete(InterviewSession).where(InterviewSession.user_id.in_(list(ids.values())))
            )
            await db.execute(delete(CreditEvent).where(CreditEvent.user_id.in_(list(ids.values()))))
            await db.execute(delete(UserPlan).where(UserPlan.user_id.in_(list(ids.values()))))
            await db.execute(delete(User).where(User.id.in_(list(ids.values()))))
            await db.execute(delete(InterviewTrack).where(InterviewTrack.id == track_id))
            await db.execute(delete(Company).where(Company.id == company_id))
            await db.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - environment, not behaviour
        pytest.skip(f"needs the dev Postgres: {exc}")


class TestRemainingIsTheSameNumberTheCandidateSees:
    async def test_remaining_matches_credits_exactly(self, population):
        """
        THE TEST THIS FILE EXISTS FOR.

        `admin._remaining_by_user` is a set-wide rewrite of `credits.remaining_for`, and the
        number it produces is quoted at a customer in an email. Two implementations of one
        piece of arithmetic is exactly the divergence the billing notes forbid, so the
        agreement is asserted against the real ledger rather than assumed from the code
        looking alike — for every account in the fixture and every metered feature, including
        the account whose consumption exceeds its allowance.
        """
        from app.services.billing.credits import remaining_for

        db, ids = population
        bulk = await _remaining_by_user(db, list(ids.values()))

        for key, uid in ids.items():
            for feature in FEATURES:
                assert bulk[uid][feature] == await remaining_for(db, uid, feature), (
                    f"{key}/{feature}: the admin list and the candidate's own balance "
                    "disagree about what is left"
                )

    async def test_an_untouched_account_has_its_whole_trial(self, population):
        db, ids = population
        bulk = await _remaining_by_user(db, [ids["fresh"]])
        assert bulk[ids["fresh"]] == {f: trial_allowance(f) for f in FEATURES}

    async def test_spending_shows_up_and_purchases_add_on_top(self, population):
        db, ids = population
        bulk = await _remaining_by_user(db, list(ids.values()))
        # CLAMPED AT ZERO, not negative. Interviews have no trial now, so a consumption puts
        # the raw net at -1 and the honest figure to show in a marketing email is 0 — "you have
        # -1 mock interviews" is both nonsense and a hint that the ledger is broken. The
        # clamping itself is covered by the test below.
        assert bulk[ids["dropper"]]["interview"] == max(0, trial_allowance("interview") - 1)
        # One consumed, five bought. Written as the formula the code uses — clamp the TOTAL,
        # not the trial portion: `max(0, trial + net)` where net is purchases minus
        # consumptions. Clamping the trial first gave 5 instead of 4, which is the kind of
        # off-by-one that reads plausibly in a marketing email and is simply wrong.
        assert bulk[ids["payer"]]["interview"] == max(
            0, trial_allowance("interview") + (5 - 1)
        )

    async def test_over_consumption_clamps_at_zero_rather_than_going_negative(self, population):
        """
        Three GDs consumed against a trial of one and a single goodwill grant. The honest
        answer is zero — a negative balance in a marketing email ("you have -1 group
        discussions") is both nonsense and a hint that the ledger is broken.
        """
        db, ids = population
        bulk = await _remaining_by_user(db, [ids["overdrawn"]])
        assert bulk[ids["overdrawn"]]["gd"] == 0


class TestActivityAndPayment:
    async def test_starts_and_completions_are_counted_separately(self, population):
        db, ids = population
        activity = await _activity_by_user(db, list(ids.values()))
        assert activity[ids["dropper"]]["sessions_started"] == 2
        assert activity[ids["dropper"]]["sessions_completed"] == 0
        assert activity[ids["waiting"]]["sessions_started"] == 1
        assert activity[ids["waiting"]]["sessions_completed"] == 1

    async def test_an_account_with_no_rows_anywhere_still_appears(self, population):
        # LEFT-JOIN semantics, done in Python: an account with nothing must come back with
        # zeroes, not be missing from the response. Dropping it would quietly remove exactly
        # the group the "your free interview is waiting" email is for.
        db, ids = population
        activity = await _activity_by_user(db, list(ids.values()))
        assert activity[ids["fresh"]]["sessions_started"] == 0
        assert activity[ids["fresh"]]["reports"] == 0
        assert activity[ids["fresh"]]["last_session_at"] is None

    async def test_a_report_is_visible_as_existing_without_any_of_its_content(self, population):
        db, ids = population
        activity = await _activity_by_user(db, list(ids.values()))
        assert activity[ids["waiting"]]["reports"] == 1
        assert activity[ids["dropper"]]["reports"] == 0

    async def test_only_a_real_purchase_counts_as_having_paid(self, population):
        """
        A 100%-off code and support goodwill write `grant`, not `purchase`. Somebody who has
        never spent money must not be mailed as a customer — and `/admin/revenue` excludes
        the same rows from revenue for the same reason.
        """
        db, ids = population
        activity = await _activity_by_user(db, list(ids.values()))
        assert activity[ids["payer"]]["purchases"] == 1
        assert activity[ids["payer"]]["last_paid_at"] is not None
        assert activity[ids["overdrawn"]]["purchases"] == 0
        assert activity[ids["overdrawn"]]["last_paid_at"] is None
        # The grant is still activity, just not payment.
        assert activity[ids["overdrawn"]]["ledger_at"] is not None


class TestTheEndpointEndToEnd:
    async def test_every_account_comes_back_segmented_and_ordered_by_recency(self, population):
        db, ids = population
        result = await admin_api.marketing_list(
            current_user=_FakeAdmin(), q=None, active=None, db=db
        )

        rows = {r.user_id: r for r in result.users if r.user_id in set(ids.values())}
        assert len(rows) == len(ids)
        assert rows[ids["fresh"]].segment == "never_started"
        # The dropper answered nothing in the fixture, so they are the "left before
        # answering" case — the one worth telling apart from a candidate who got partway.
        assert rows[ids["dropper"]].segment in ("left_before_answering", "stopped_partway")
        # A SCORED REPORT NOW OUTRANKS EVERYTHING, including having paid. This fixture's
        # report carries overall_score=71.5, so this account is somebody the product worked
        # end to end for — which is the more useful thing to know about them than how they
        # arrived. `report_waiting` kept its name and changed its meaning: a report row that
        # was never scored. `unscored` below covers it.
        assert rows[ids["waiting"]].segment == "report_generated"
        assert rows[ids["waiting"]].scored_reports == 1
        assert rows[ids["waiting"]].best_score == 71.5
        assert rows[ids["unscored"]].segment == "report_waiting"
        assert rows[ids["unscored"]].scored_reports == 0
        assert rows[ids["unscored"]].best_score is None
        # The payer ALSO has a scored report, so they land in `report_generated` too — and
        # that is the ordering working rather than a surprise. Paid-ness is still on the row
        # as its own columns, which is why nothing is lost by it not being the segment.
        assert rows[ids["payer"]].segment == "report_generated"
        assert rows[ids["payer"]].ever_paid is True
        assert rows[ids["payer"]].purchases == 1
        assert rows[ids["waiting"]].ever_paid is False

        # WHO IS LEFT IN `customer`, now that a scored report outranks it: somebody who has
        # paid and has not practised yet. A real and useful group — they are the ones to tell
        # to start, not to sell to — and the reason the segment is still worth having.
        assert rows[ids["buyer"]].segment == "customer"
        assert rows[ids["buyer"]].ever_paid is True
        assert rows[ids["buyer"]].scored_reports == 0

        # Most recently active first, and the account that has never done anything is last
        # rather than first — the order somebody actually mails in.
        ordered = [r.user_id for r in result.users if r.user_id in set(ids.values())]
        assert ordered.index(ids["waiting"]) < ordered.index(ids["dropper"])
        assert ordered[-1] == ids["fresh"]

    async def test_the_segment_counts_add_up_to_the_rows_returned(self, population):
        db, _ids = population
        result = await admin_api.marketing_list(
            current_user=_FakeAdmin(), q=None, active=None, db=db
        )
        assert sum(s.count for s in result.segments) == result.returned == len(result.users)

    async def test_the_feature_columns_are_named_by_the_server(self, population):
        # The browser must not hard-code either the order or the label — `FEATURE_LABELS` is
        # the same copy the 402 paywall message is built from, so a feature cannot be called
        # one thing to a candidate and another to the person mailing them.
        db, _ids = population
        result = await admin_api.marketing_list(
            current_user=_FakeAdmin(), q=None, active=None, db=db
        )
        assert [f.feature for f in result.features] == list(FEATURES)
        assert all(f.label and f.label != f.feature for f in result.features)

    async def test_searching_by_email_narrows_the_list(self, population):
        db, ids = population
        target = next(
            r
            for r in (
                await admin_api.marketing_list(
                    current_user=_FakeAdmin(), q=None, active=None, db=db
                )
            ).users
            if r.user_id == ids["payer"]
        )
        narrowed = await admin_api.marketing_list(
            current_user=_FakeAdmin(), q=target.email, active=None, db=db
        )
        assert [r.user_id for r in narrowed.users] == [ids["payer"]]

    async def test_an_admin_row_says_unlimited_rather_than_a_number(self, population):
        """
        `credits.consume` returns before it looks at any balance for an admin, so a figure in
        that column would be meaningless — and "you have 1 interview left" quoted at your own
        operator account in a marketing email is embarrassing in a specific, avoidable way.
        """
        db, ids = population
        from app.models.user import User

        target = await db.get(User, ids["fresh"])
        target.is_admin = True
        await db.commit()
        try:
            result = await admin_api.marketing_list(
                current_user=_FakeAdmin(), q=None, active=None, db=db
            )
            row = next(r for r in result.users if r.user_id == ids["fresh"])
            assert row.unlimited is True
        finally:
            target.is_admin = False
            await db.commit()


class TestQueryCount:
    async def test_the_statement_count_does_not_grow_with_the_number_of_accounts(
        self, population
    ):
        """
        THE N+1 GUARD, MEASURED RATHER THAN ASSERTED FROM THE SOURCE.

        Per-user balances across every account is where a loop of queries turns an admin page
        into a timeout, and it arrives gradually — the page is fine at ten accounts and dead
        at two thousand, so it reads as "the admin page got slow" rather than as a bug with a
        cause. Counting statements for one account and then for five is the only assertion
        that actually fails when someone adds a convenient per-row lookup.
        """
        db, ids = population

        from app.models.user import User

        payer = await db.get(User, ids["payer"])

        one = _CountingSession(db)
        await admin_api.marketing_list(
            current_user=_FakeAdmin(), q=payer.email, active=None, db=one
        )

        several = _CountingSession(db)
        await admin_api.marketing_list(current_user=_FakeAdmin(), q=None, active=None, db=several)

        assert several.executions == one.executions, (
            f"{one.executions} statements for one account and {several.executions} for the "
            "whole list — something in here is querying per row"
        )
        # Eight, whatever the size of the list: the total count, the accounts themselves, the
        # balance aggregate, and one grouped aggregate each for sessions, ANSWERS, reports,
        # FEEDBACK and the ledger. Pinned so that adding a ninth is a decision somebody makes
        # on purpose rather than by reaching for one more query from inside the loop.
        #
        # It was six, then seven, now eight. The answers aggregate split what used to be one
        # `dropped_off` bucket into "answered some, then stopped" and "left before answering
        # anything"; the feedback aggregate carries what the account thinks of us. Each is a
        # fixed cost for the whole list, and the assertion ABOVE is the one that actually
        # matters — this number growing is fine, growing WITH THE NUMBER OF ACCOUNTS is not.
        assert several.executions == 8


class TestAScoredReportOutranksHavingPaid:
    """
    THE ORDERING QUESTION, pinned because getting it wrong is silent.

    `customer` used to be first, on the reasoning that you do not send an offer to somebody who
    has just bought. That was right while interviews had a free trial. They do not any more —
    every interview is paid — so almost anybody with a report has also paid, and a
    "report generated" segment placed below `customer` would be a bucket that is definitionally
    empty. Nobody would notice: the screen would simply never show it.
    """

    def test_a_scored_report_wins_over_having_paid(self):
        assert (
            _segment_of(True, reports=1, completed=1, started=1, answers=8, scored_reports=1)
            == "report_generated"
        )

    def test_paying_without_a_scored_report_is_still_a_customer(self):
        # The segment stays reachable and stays useful: they have paid and not practised, so
        # the email tells them to start rather than selling them anything.
        assert (
            _segment_of(True, reports=0, completed=0, started=0, answers=0, scored_reports=0)
            == "customer"
        )

    def test_a_report_row_with_no_score_is_not_a_delivered_report(self):
        # An unscored placeholder is written whenever generation fails. Counting it as a
        # delivered report would tell the operator the product worked for somebody it did not.
        assert (
            _segment_of(False, reports=1, completed=1, started=1, answers=8, scored_reports=0)
            == "report_waiting"
        )

    def test_the_new_segment_is_declared_above_customer(self):
        # Precedence is the definition, and it lives in two places that must agree: the order
        # of _SEGMENTS and the order of the tests in _segment_of. This pins the table.
        keys = [seg for seg, _label, _happened, _pitch in _SEGMENTS]
        assert keys.index("report_generated") < keys.index("customer")

    def test_no_segment_still_advertises_a_report_unlock(self):
        # Two segment strings named a Rs 49 report unlock that no longer exists at any price —
        # report_access.py is gone and the report comes with the interview. Copy that describes
        # a deleted paywall is how an operator ends up mailing an offer nobody can accept.
        for _seg, label, happened, pitch in _SEGMENTS:
            blob = f"{label} {happened} {pitch}".lower()
            assert "unlock" not in blob, f"{label} still mentions an unlock"
            assert "₹49" not in blob and "₹50" not in blob, f"{label} still names a price"
