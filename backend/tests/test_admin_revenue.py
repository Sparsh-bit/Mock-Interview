"""
Revenue, and the two decisions that make the figure trustworthy.

WHY THIS FILE IS MOSTLY ABOUT ONE SQL STRING. The revenue endpoint is a query, and the
queries that matter cannot run here — `conftest.py` points at a Postgres that only
`test_integration.py` reaches. What CAN be pinned without a database is the pair of choices
that decide whether the number is right, and both are the kind that stay right only if
something checks:

1. Money comes from `detail.amount_paise`, not from `delta`. `delta` is a signed count of
   ITEMS — +5 for a five-pack — so summing it gives units sold and calls it rupees. That
   mistake produces a number that is plausible, wrong, and wrong in a stable direction, so
   nobody notices until it is compared against the gateway.

2. The sum is per PAYMENT, not per row. `payment_ref` is indexed but not unique, and the
   webhook and the browser callback can both grant one payment — each checks the ledger
   first, but that check is a read-then-write with a window in it. Counting rows turns one
   double-grant into double revenue, which flatters us, which is the direction an error is
   least likely to be questioned.

The arithmetic tests below are not filler: money is summed as integers and divided exactly
once, at the edge. A float rupee that accumulates through a sum is how a revenue figure ends
up disagreeing with the payment gateway by a paisa, and a figure that disagrees once is a
figure nobody trusts again.
"""

from __future__ import annotations

import pytest

from app.api.v1.admin import _PAISE_PER_RUPEE, _REVENUE_ROWS, _inr


class TestMoneyConversion:
    """Paise are integers. Rupees are a display format, produced once, at the end."""

    @pytest.mark.parametrize(
        ("paise", "rupees"),
        [
            (0, 0.0),
            (1, 0.01),
            (49_00, 49.0),
            (199_00, 199.0),
            (1_234_56, 1234.56),
        ],
    )
    def test_paise_render_as_the_rupee_figure_a_human_expects(self, paise, rupees):
        assert _inr(paise) == rupees

    def test_the_divisor_is_the_real_one(self):
        # Guards against someone "simplifying" this to 1000 after seeing a currency with
        # three decimal places. Razorpay quotes paise; a wrong divisor is a 10x revenue
        # figure that still looks like money.
        assert _PAISE_PER_RUPEE == 100

    def test_summing_in_paise_does_not_drift(self):
        """
        THE REASON MONEY IS NOT A FLOAT HERE.

        Three ₹19.90 payments is exactly ₹59.70. Convert each to rupees first and the sum
        is 59.699999999999996 — off by a hair, in a way that renders as a long decimal tail
        in the UI and disagrees with the gateway.

        Note this does NOT reproduce for every amount: ten ₹49.00 payments happen to sum
        cleanly as floats. That is exactly what makes it dangerous — it survives the
        example you check by hand and appears later on a price you did not think about.
        Summing integers first removes the class of bug rather than the instance.
        """
        payments = [19_90] * 3
        assert sum(payments) == 59_70
        assert _inr(sum(payments)) == 59.7

        naive = sum(p / 100 for p in payments)
        assert naive != 59.7
        assert repr(naive) == "59.699999999999996"


class TestTheRevenueQuery:
    """
    Structural pins on the query. Cheap, and they catch the edits that silently change
    what the number means — which is the only kind of edit this file can catch at all.
    """

    def test_only_purchases_count_as_revenue(self):
        # A 100%-off code writes kind='grant' with charged_paise 0, and support goodwill
        # writes 'grant' too. Both are product given away, neither is money taken.
        assert "kind = 'purchase'" in _REVENUE_ROWS

    def test_the_money_comes_from_the_captured_amount_not_the_item_count(self):
        assert "detail->>'amount_paise'" in _REVENUE_ROWS
        # `delta` is the item count. If it ever appears in this query, the figure has
        # stopped being revenue and nobody will be able to tell by looking at it.
        assert "delta" not in _REVENUE_ROWS

    def test_revenue_is_deduped_per_payment(self):
        """
        The guard against a double-grant becoming double revenue.

        Two paths can insert for one payment — billing.py's browser callback and its
        webhook. Both check the ledger first; neither check is atomic.
        """
        assert "DISTINCT ON" in _REVENUE_ROWS
        assert "coalesce(payment_ref, id::text)" in _REVENUE_ROWS

    def test_a_purchase_without_a_payment_reference_still_counts_once(self):
        """
        `coalesce(payment_ref, id::text)` rather than a bare `payment_ref`.

        Deduping on a nullable column collapses every NULL into one group, so a set of
        reference-less purchases would count as a single sale. Falling back to the row's
        own id makes each one distinct, which is the honest reading: we cannot prove they
        are the same payment, so we must not merge them.
        """
        assert "coalesce(payment_ref, id::text)" in _REVENUE_ROWS
        assert "DISTINCT ON (payment_ref)" not in _REVENUE_ROWS

    def test_postgres_requires_the_order_by_to_match_the_distinct_on(self):
        # DISTINCT ON without a leading matching ORDER BY is a Postgres error, not a
        # silently different result — but it is an error that only appears at runtime,
        # against a real database, on a page an admin opens rarely.
        assert "ORDER BY coalesce(payment_ref, id::text)" in _REVENUE_ROWS


class TestVectorCacheStorageDegrades:
    """
    The storage figure feeds an admin panel, so a missing table greys out a number rather
    than 500-ing the page — the same choice `stats()` already makes.
    """

    async def test_a_failing_query_returns_a_complete_zeroed_shape(self):
        from app.services.ai import vector_cache

        class _ExplodingDb:
            async def execute(self, *_args, **_kwargs):
                raise RuntimeError("relation \"ai_cache\" does not exist")

        result = await vector_cache.storage(_ExplodingDb())

        # `available: False` is the signal the UI needs to distinguish "the cache is empty"
        # from "we could not ask" — two very different things that both render as zero.
        assert result["available"] is False
        # Every key the happy path returns must still be present, or the frontend reads
        # undefined and renders NaN.
        for key in (
            "total_bytes",
            "table_bytes",
            "index_bytes",
            "rows",
            "hits",
            "features",
            "max_rows_per_feature",
            "embedding_dim",
        ):
            assert key in result, f"missing {key} on the degraded path"

    async def test_the_degraded_path_still_reports_the_real_configuration(self):
        # Rows and hits are unknowable without the table; the dimension and the LRU cap are
        # constants in the code and are still true when the query fails.
        from app.models.ai_cache import EMBEDDING_DIM
        from app.services.ai import vector_cache

        class _ExplodingDb:
            async def execute(self, *_args, **_kwargs):
                raise RuntimeError("boom")

        result = await vector_cache.storage(_ExplodingDb())
        assert result["embedding_dim"] == EMBEDDING_DIM
        assert result["max_rows_per_feature"] == vector_cache._MAX_ROWS_PER_FEATURE
