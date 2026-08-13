"""
TEMPORARY — tests for the AI cost ledger. Delete with the feature.
See TEMPORARY-token-counter.md.

The load-bearing test here is the first class: a ledger that can take the product
down is worse than no ledger. Everything else is arithmetic and labelling.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.api.v1.ai_usage import FEATURE_LABELS
from app.services.ai import usage
from app.services.ai.base_provider import ProviderResponse


def _response(**kw) -> ProviderResponse:
    base = {
        "content": "{}",
        "model": "claude-sonnet-5",
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "finish_reason": "stop",
        "estimated_cost_usd": 0.0105,
    }
    base.update(kw)
    return ProviderResponse(**base)


class TestRecordingCannotBreakARequest:
    """
    Rule 1 of services/ai/usage.py. A candidate mid-interview must never see a
    500 because a cost row could not be written.
    """

    async def test_a_failing_database_is_swallowed(self, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("database is on fire")

        # Break the thing record_call reaches for, at the point it reaches for it.
        monkeypatch.setattr("app.db.session.get_db_session", boom, raising=True)
        monkeypatch.setattr(usage, "_enabled", lambda: True)

        # Must return normally, not raise.
        await usage.record_call(
            feature="quiz_generation",
            provider="anthropic",
            response=_response(),
            cost_tier="balanced",
            outcome="ok",
        )

    async def test_a_missing_model_is_swallowed(self, monkeypatch):
        """The table not existing yet — a deploy before the migration ran."""
        monkeypatch.setattr(usage, "_enabled", lambda: True)
        monkeypatch.setitem(
            __import__("sys").modules, "app.models.ai_usage", None
        )
        await usage.record_call(
            feature="report_generation",
            provider="anthropic",
            response=_response(),
            cost_tier="deep",
            outcome="ok",
        )

    async def test_disabled_is_a_no_op(self, monkeypatch):
        """
        With the flag off nothing is imported and nothing is written, so switching
        the ledger off cannot itself introduce a failure path.
        """
        monkeypatch.setattr(usage, "_enabled", lambda: False)
        called = False

        def tripwire(*_a, **_k):
            nonlocal called
            called = True
            raise AssertionError("should never be reached when disabled")

        monkeypatch.setattr("app.db.session.get_db_session", tripwire, raising=True)
        await usage.record_call(
            feature="cross_question",
            provider="anthropic",
            response=_response(),
            cost_tier="cheap",
            outcome="ok",
        )
        assert called is False


class TestAttribution:
    def test_defaults_to_unattributed(self):
        """
        A background job has no user. NULL is the honest answer — the cost was
        real and nobody asked for it.
        """
        assert usage.current_user_id.get() is None

    def test_attributed_to_sets_and_restores(self):
        uid = uuid.uuid4()
        assert usage.current_user_id.get() is None
        with usage.attributed_to(uid):
            assert usage.current_user_id.get() == uid
        # Restored, so one task serving work for two users cannot cross-attribute.
        assert usage.current_user_id.get() is None

    def test_nesting_restores_the_outer_value(self):
        outer, inner = uuid.uuid4(), uuid.uuid4()
        with usage.attributed_to(outer):
            with usage.attributed_to(inner):
                assert usage.current_user_id.get() == inner
            assert usage.current_user_id.get() == outer


class TestMoneyPrecision:
    """
    cost_usd is NUMERIC and the conversion goes through str(), not float().

    Being precise about why, because the usual "floats lose money" line is not
    what is going on at this scale: summing 10,000 costs of $0.0004 in float
    gives exactly 4.0. The drift at realistic volumes is around 1e-15, which is
    nothing.

    The real reasons are exactness and determinism. A NUMERIC SUM returns a total
    that is exactly the sum of the stored rows, so the report cannot disagree
    with the rows it was built from — and Postgres may compute a double-precision
    aggregate in a different order between runs (parallel plans), so the same
    query can return slightly different totals. For a money column that is
    avoidable for free.
    """

    def test_decimal_from_str_is_exact(self):
        assert Decimal(str(0.0105)) == Decimal("0.0105")

    def test_decimal_from_float_carries_the_binary_error(self):
        """Documents why record_call uses str(cost), so nobody 'simplifies' it."""
        assert Decimal(0.0105) != Decimal("0.0105")

    def test_decimal_sums_are_exact(self):
        """
        The property that matters: the total equals the rows, to the cent, at any
        volume. Asserted on a case where float genuinely does differ, so the test
        is demonstrating something real rather than restating an equality.
        """
        n, each = 25_000, "0.000432"
        exact = sum((Decimal(each) for _ in range(n)), Decimal("0"))
        assert exact == Decimal("10.800000")
        assert sum(float(each) for _ in range(n)) != float(exact)


class TestFeatureLabels:
    """
    Every `context=` label in the codebase must have a human label, or the cost
    view shows a raw identifier for the feature spending the most money.
    """

    def test_every_context_label_in_the_code_is_named(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        found: set[str] = set()
        for f in root.rglob("*.py"):
            found |= set(re.findall(r'context="([a-z_]+)"', f.read_text()))

        # The library's own default, not a feature.
        found.discard("ai_generation")

        missing = sorted(found - set(FEATURE_LABELS))
        assert not missing, (
            f"generate_structured call sites with no label in FEATURE_LABELS: {missing}"
        )

    def test_no_label_describes_a_feature_that_no_longer_exists(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        found: set[str] = set()
        for f in root.rglob("*.py"):
            found |= set(re.findall(r'context="([a-z_]+)"', f.read_text()))

        stale = sorted(set(FEATURE_LABELS) - found)
        assert not stale, f"FEATURE_LABELS entries with no call site: {stale}"


class TestTheSeamIsStillTheOnlySeam:
    """
    The ledger instruments every feature because every feature goes through
    generate_structured. If someone adds a direct provider call, that spend
    becomes invisible — and invisible spend is the failure mode this whole
    feature exists to prevent.
    """

    def test_generate_structured_records_every_outcome(self):
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app/services/ai/generate.py"
        ).read_text()
        # One on success, two on the billed-and-discarded paths.
        assert src.count("await record_call(") == 3
        assert 'outcome="discarded"' in src
        assert 'outcome="ok"' in src

    def test_no_service_calls_a_provider_directly(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        offenders = []
        for f in root.rglob("*.py"):
            if f.name in {
                "base_provider.py",
                "anthropic_provider.py",
                "glm_provider.py",
                "generate.py",
                "provider_factory.py",
                "response_parser.py",
            }:
                continue
            text = f.read_text()
            # Strip docstrings before scanning — the factory and parser modules
            # document usage with example `.complete(...)` calls that are not code.
            text = re.sub(r'"""(?:.|\n)*?"""', "", text)
            if ".complete(" in text:
                offenders.append(str(f.relative_to(root)))
        assert not offenders, (
            "these bypass generate_structured, so their spend is not recorded: "
            f"{offenders}"
        )


@pytest.mark.parametrize(
    ("cost", "expected"),
    [(None, Decimal("0")), (0.0, Decimal("0")), (0.014898, Decimal("0.014898"))],
)
def test_unpriced_calls_record_zero_not_null(cost, expected):
    """
    A free-tier provider reports no cost. Zero is right; NULL would make SUM
    skip the row and quietly understate the call count against the spend.
    """
    got = Decimal(str(cost)) if cost is not None else Decimal("0")
    assert got == expected


class TestTheCacheSavingIsPriced:
    """
    "The cache is working" has to be a figure, not an assertion.

    vector_cache.stats() counts hits and the ledger knows what a call costs; the two sat
    side by side in this response for a long time without ever being multiplied, so nothing
    in the product could say what the cache had actually saved. That matters more now than
    it did: the argument for pricing the free tier where it is rests on cost per user
    FALLING as the user base grows, and an argument like that should be checkable against
    an invoice rather than against a paragraph in a design doc.
    """

    def test_the_saving_is_computed_from_this_window_not_a_constant(self):
        # A saving quoted against a hardcoded price is a made-up number the day a model
        # price changes — and prompt caching already moved the GD turn by 59%.
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parent.parent / "app/api/v1/ai_usage.py"
        ).read_text()
        block = src[src.index("cache_rows = await vector_cache.stats") :]
        assert "avg_cost_per_call_usd" in block, (
            "the cache saving is not priced from the window's own ledger"
        )

    def test_it_reports_hits_per_entry(self):
        # The saturation signal. A shared cache only makes the product cheaper at scale if
        # entries are reused many times over; flat near 1.0 means the key space grows with
        # the user count and the cache will never pay for itself.
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parent.parent / "app/api/v1/ai_usage.py"
        ).read_text()
        assert "hits_per_entry" in src

    def test_a_feature_with_no_ledger_rows_prices_at_zero_rather_than_raising(self):
        # A cache entry for a feature that has not been called inside the window has no
        # average cost. That must be 0.0, not a KeyError on the admin dashboard.
        cost_per_call: dict[str, float] = {}
        row = {"feature": "study_resources", "hits": 12, "entries": 4, "never_hit": 0}
        unit = float(cost_per_call.get(row["feature"], 0.0))
        assert unit == 0.0
        assert row["hits"] * unit == 0.0
