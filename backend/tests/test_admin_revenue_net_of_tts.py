"""
Speech is in the margin now — tests/test_admin_revenue_net_of_tts.py

`GET /admin/revenue` reported gross with no cost beside it, and `plans.py` prices every item
against AI cost alone. Speech is a second variable cost, metered per character, billed by a
different vendor, and — per `services/tts/base.py`, measured rather than estimated — up to
TWELVE TIMES the AI cost of the same group-discussion round on the wrong vendor. Omitting it
did not make the margin incomplete. It made it wrong, and wrong in the direction that
flatters us, which is the direction an error is least likely to be questioned.

It could not be included before this change, and that is worth being precise about: the only
record of speech spend was `services/tts/spend.py`, an `INCRBYFLOAT` on a key named for the
current UTC day with a 48-hour TTL and no user, vendor or feature on it. A thirty-day margin
could not include it even in principle. `tts_usage` is the ledger that makes the join
possible; the Redis counter stays as the budget brake on the hot path.

WHAT THESE TESTS PROTECT, in order of how badly each would hurt:

  1. THE ARITHMETIC. Contribution is gross minus BOTH costs, converted once, at a stated
     rate, and never clamped — a negative margin is the only finding on that page worth
     acting on immediately.
  2. MISSING DATA IS REPORTED AS MISSING. Either ledger can be off by configuration or
     absent from an unmigrated database. A margin that reads absent cost as zero cost is
     precisely the failure this change exists to remove, and it is invisible.
  3. THE CACHE HIT RATE IS COUNTED IN CHARACTERS. A hit on a 20-character greeting and one
     on a 400-character panel turn are not the same saving.
  4. ONE FX RATE IN THE PRODUCT. Two would mean the margin script and the admin page
     disagreeing about the same month.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import delete

from app.api.v1.admin import _INR_PER_USD, _PAISE_PER_RUPEE, _inr
from app.core.config import settings
from app.main import app


def _token(user_id: uuid.UUID) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": f"rev-{user_id}@example.test",
            "aud": settings.SUPABASE_JWT_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


class TestTheFxRateIsDefinedOnce:
    def test_the_admin_page_and_the_margin_script_use_the_same_rate(self):
        """
        Two rates would mean `/admin/revenue` and `scripts/item_margin.py` reporting
        different margins for the same month, with nothing in either output saying why.
        """
        from scripts.item_margin import _INR_PER_USD as SCRIPT_RATE

        assert _INR_PER_USD == SCRIPT_RATE

    def test_the_rate_is_the_one_plans_py_states(self):
        """
        plans.py gives an interview's AI cost as "~$0.154 (₹13)". That pairing is 84.4, and
        taking the rate from the repo's own figures is what stops this page and that table
        disagreeing about what ₹49 is worth.
        """
        assert round(13 / 0.154, 1) == pytest.approx(84.4, abs=0.5)
        assert _INR_PER_USD == 84.4


@pytest.mark.asyncio
class TestRevenueNetsOutBothCosts:
    @pytest.fixture
    async def admin(self):
        from app.db.session import AsyncSessionFactory, engine
        from app.models.ai_usage import AIUsage
        from app.models.base import Base
        from app.models.billing import CreditEvent
        from app.models.tts_usage import TTSUsage
        from app.models.user import User

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        uid = uuid.uuid4()
        async with AsyncSessionFactory() as db:
            # A clean window: this endpoint aggregates the WHOLE table over `days`, so any
            # rows left by another test would make the arithmetic below unverifiable.
            since = datetime.now(UTC) - timedelta(days=2)
            for model in (AIUsage, TTSUsage):
                await db.execute(delete(model).where(model.created_at >= since))
            await db.execute(delete(CreditEvent).where(CreditEvent.created_at >= since))
            db.add(
                User(
                    id=uid,
                    supabase_uid=str(uid),
                    email=f"rev-{uid}@example.test",
                    is_active=True,
                    is_admin=True,
                )
            )
            await db.commit()
        return uid

    async def _revenue(self, admin_id: uuid.UUID, days: int = 1) -> dict:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            res = await ac.get(
                f"/api/v1/admin/revenue?days={days}",
                headers={"Authorization": f"Bearer {_token(admin_id)}"},
            )
        assert res.status_code == 200, res.text
        return res.json()

    async def _seed(
        self,
        *,
        user_id: uuid.UUID,
        gross_paise: int = 0,
        ai_usd: str = "0",
        tts: tuple[str, int, bool] | None = None,
    ) -> None:
        from app.db.session import AsyncSessionFactory
        from app.models.ai_usage import AIUsage
        from app.models.billing import CreditEvent
        from app.models.tts_usage import TTSUsage

        now = datetime.now(UTC)
        async with AsyncSessionFactory() as db:
            if gross_paise:
                db.add(
                    CreditEvent(
                        id=uuid.uuid4(),
                        created_at=now,
                        user_id=user_id,
                        feature="interview",
                        kind="purchase",
                        delta=1,
                        payment_ref=f"pay_{uuid.uuid4().hex[:12]}",
                        detail={"amount_paise": gross_paise, "item_id": "interview_1"},
                    )
                )
            if ai_usd != "0":
                db.add(
                    AIUsage(
                        created_at=now,
                        feature="report_generation",
                        provider="anthropic",
                        model="claude-sonnet-5",
                        cost_tier="standard",
                        outcome="ok",
                        cost_usd=Decimal(ai_usd),
                        user_id=user_id,
                    )
                )
            if tts is not None:
                usd, characters, cached = tts
                db.add(
                    TTSUsage(
                        created_at=now,
                        provider="fish",
                        model="s1",
                        speaker="Riya",
                        characters=characters,
                        cached=cached,
                        cost_usd=Decimal(usd),
                        user_id=user_id,
                    )
                )
            await db.commit()

    async def test_speech_cost_appears_at_all(self, admin):
        """
        THE WHOLE POINT. Before this change there was no field on this response that could
        hold it, and no table it could have come from.
        """
        await self._seed(user_id=admin, tts=("0.117000", 7_800, False))
        body = await self._revenue(admin)
        assert body["costs"]["tts_available"] is True
        assert body["costs"]["tts_usd"] == pytest.approx(0.117)
        assert body["costs"]["tts_characters"] == 7_800

    async def test_the_before_and_after_on_one_group_discussion(self, admin):
        """
        THE WORKED EXAMPLE, with the real constants.

        A ₹39 group discussion. Its AI cost is $0.1423 (docs/AI-COST-MODEL.md, from the
        logged ledger) and its speech is 7,800 characters — 26 panel turns, from
        services/tts/base.py — none of which can ever hit the audio cache, because every GD
        turn is unique text.

        BEFORE: gross ₹39, no cost on the page at all. plans.py quotes 69% on AI alone.
        AFTER : at Fish's $15/M that is $0.117 of speech, so ₹39 gross against
                ($0.1423 + $0.117) x 84.4 = ₹21.89 of variable cost, leaving ₹17.11 —
                roughly 44%, against the 69% the AI-only figure implies.

        The 25-point gap is one item's speech bill. That is the finding.
        """
        await self._seed(
            user_id=admin,
            gross_paise=3_900,
            ai_usd="0.142300",
            tts=("0.117000", 7_800, False),
        )
        body = await self._revenue(admin)

        assert body["gross_inr"] == 39.0
        variable_usd = 0.1423 + 0.117
        assert body["costs"]["variable_usd"] == pytest.approx(variable_usd)

        expected_paise = 3_900 - int(round(variable_usd * _INR_PER_USD * _PAISE_PER_RUPEE))
        assert body["contribution_paise"] == expected_paise
        assert body["contribution_inr"] == _inr(expected_paise)
        # ~44%, and decisively not the ~63% that leaving speech out would have produced.
        assert 40 < body["contribution_margin_pct"] < 48
        ai_only_pct = (3_900 - 0.1423 * _INR_PER_USD * 100) / 3_900 * 100
        assert body["contribution_margin_pct"] < ai_only_pct - 20

    async def test_a_negative_margin_is_reported_rather_than_clamped(self, admin):
        """
        The only finding on that page worth acting on immediately. `scripts/item_margin.py`
        shows a group discussion at ElevenLabs Creator rates has a margin of -118%, so this
        is not a hypothetical shape — a max(0, ...) anywhere in the arithmetic would hide the
        one number that matters.
        """
        await self._seed(
            user_id=admin,
            gross_paise=3_900,
            ai_usd="0.142300",
            tts=("0.858000", 7_800, False),  # ElevenLabs Creator, flash_v2_5
        )
        body = await self._revenue(admin)
        assert body["contribution_paise"] < 0
        assert body["contribution_margin_pct"] < 0

    async def test_a_cache_hit_is_free_and_still_counted(self, admin):
        """
        A hit costs nothing and is recorded anyway, with the characters it avoided.
        scripts/item_margin.py shows the hit rate IS the speech economics — it is the whole
        reason an interview's margin survives a vendor a group discussion's does not — so a
        ledger of misses alone could measure the bill and never measure what reduces it.
        """
        await self._seed(user_id=admin, tts=("0", 3_600, True))
        await self._seed(user_id=admin, tts=("0.018000", 1_200, False))
        body = await self._revenue(admin)

        assert body["costs"]["tts_usd"] == pytest.approx(0.018)
        assert body["costs"]["tts_characters"] == 4_800
        assert body["costs"]["tts_characters_cached"] == 3_600
        # BY CHARACTERS, NOT BY UTTERANCE: 3,600 of 4,800 is 75%, where counting the two rows
        # equally would have said 50% and understated the saving by a third.
        assert body["costs"]["tts_cache_hit_pct"] == pytest.approx(75.0)

    async def test_speech_is_broken_out_per_vendor(self, admin):
        """
        The vendor choice is a ten-fold difference in the bill and it is a deployment
        setting, so a window that spans a switch has to show both halves rather than one
        blended number that describes neither.
        """
        from app.db.session import AsyncSessionFactory
        from app.models.tts_usage import TTSUsage

        async with AsyncSessionFactory() as db:
            db.add(
                TTSUsage(
                    created_at=datetime.now(UTC),
                    provider="elevenlabs",
                    model="eleven_flash_v2_5",
                    speaker="Arjun",
                    characters=1_000,
                    cached=False,
                    cost_usd=Decimal("0.110000"),
                    user_id=admin,
                )
            )
            await db.commit()
        await self._seed(user_id=admin, tts=("0.015000", 1_000, False))

        body = await self._revenue(admin)
        by_provider = {v["provider"]: v for v in body["costs"]["tts_by_provider"]}
        assert set(by_provider) == {"fish", "elevenlabs"}
        assert by_provider["elevenlabs"]["cost_usd"] == pytest.approx(0.11)
        assert by_provider["fish"]["cost_usd"] == pytest.approx(0.015)
        # Sorted by spend, so the expensive one is the one you read first.
        assert body["costs"]["tts_by_provider"][0]["provider"] == "elevenlabs"

    async def test_gross_is_untouched_by_any_of_this(self, admin):
        """
        `gross_paise` stays comparable to the Razorpay dashboard's captured total. Netting
        cost INTO it — rather than reporting cost beside it — would break the one figure on
        this page that reconciles against an external source.
        """
        await self._seed(
            user_id=admin, gross_paise=4_900, ai_usd="0.500000", tts=("0.500000", 5_000, False)
        )
        body = await self._revenue(admin)
        assert body["gross_paise"] == 4_900
        assert body["gross_inr"] == 49.0
        assert body["contribution_paise"] < body["gross_paise"]

    async def test_a_switched_off_ledger_reads_as_unavailable_not_as_zero_cost(
        self, admin, monkeypatch
    ):
        """
        THE FAILURE THIS WHOLE CHANGE EXISTS TO REMOVE, in its last hiding place. A margin
        that treats absent cost data as no cost looks authoritative and is nonsense, and the
        two ledgers can be switched off independently or be missing from a database that has
        not been migrated yet.
        """
        await self._seed(user_id=admin, gross_paise=4_900, tts=("0.400000", 5_000, False))
        monkeypatch.setattr(settings, "TTS_USAGE_LEDGER_ENABLED", False)

        body = await self._revenue(admin)
        assert body["costs"]["tts_available"] is False
        assert body["contribution_complete"] is False, (
            "the page must say the figure is an upper bound rather than presenting it as a "
            "margin"
        )

    async def test_both_ledgers_present_marks_the_figure_complete(self, admin):
        await self._seed(
            user_id=admin, gross_paise=4_900, ai_usd="0.100000", tts=("0.010000", 500, False)
        )
        body = await self._revenue(admin)
        assert body["costs"]["ai_available"] is True
        assert body["costs"]["tts_available"] is True
        assert body["contribution_complete"] is True

    async def test_the_rate_used_is_reported_with_the_figures_it_produced(self, admin):
        """A margin computed at an unstated FX rate is a margin nobody can check."""
        body = await self._revenue(admin)
        assert body["costs"]["inr_per_usd"] == _INR_PER_USD

    async def test_an_ordinary_account_cannot_see_any_of_it(self, admin):
        """
        Cost, margin and revenue are data about the business. The endpoint already took
        `AdminUser`; this pins that the new block did not arrive on a route that stopped
        checking.
        """
        from app.db.session import AsyncSessionFactory
        from app.models.user import User

        uid = uuid.uuid4()
        async with AsyncSessionFactory() as db:
            db.add(
                User(
                    id=uid,
                    supabase_uid=str(uid),
                    email=f"plain-{uid}@example.test",
                    is_active=True,
                    is_admin=False,
                )
            )
            await db.commit()

        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            res = await ac.get(
                "/api/v1/admin/revenue?days=1",
                headers={"Authorization": f"Bearer {_token(uid)}"},
            )
        assert res.status_code == 403
        assert "contribution_inr" not in res.text


@pytest.mark.asyncio
class TestTheSpeechLedgerIsActuallyWritten:
    """
    A margin figure joined against an empty table is a margin of 100%.

    The ledger only means anything if `/tts/speak` writes to it on BOTH paths — the paid
    synthesis and the cache hit — so these check the writer and the seam rather than the
    aggregation, which the tests above cover.
    """

    async def test_it_writes_a_row_with_the_cost_and_the_characters(self):
        from sqlalchemy import select

        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.tts_usage import TTSUsage
        from app.services.tts.usage import record_synthesis

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        await record_synthesis(
            provider="fish",
            model="s1",
            speaker="Meera",
            characters=312,
            cost_usd=0.00468,
            cached=False,
            user_id=None,
        )

        async with AsyncSessionFactory() as db:
            row = await db.scalar(
                select(TTSUsage)
                .where(TTSUsage.speaker == "Meera", TTSUsage.characters == 312)
                .order_by(TTSUsage.created_at.desc())
                .limit(1)
            )
        assert row is not None
        assert row.provider == "fish"
        assert row.cached is False
        assert float(row.cost_usd) == pytest.approx(0.00468)

    async def test_a_failed_write_never_reaches_the_caller(self, monkeypatch):
        """
        RULE ONE, INHERITED FROM services/ai/usage.py. Speech is the one feature in this
        product designed to degrade silently to browser voices; an accounting write that can
        503 a group discussion is worse than no accounting at all.
        """
        import app.services.tts.usage as usage_module

        def _explode(*_args, **_kwargs):
            raise RuntimeError("database is on fire")

        monkeypatch.setattr("app.db.session.get_db_session", _explode)
        # Must return normally rather than raising.
        await usage_module.record_synthesis(
            provider="fish",
            model="s1",
            speaker="Riya",
            characters=100,
            cost_usd=0.0015,
            cached=False,
            user_id=None,
        )

    async def test_the_flag_switches_it_off_without_a_deploy(self, monkeypatch):
        from sqlalchemy import func, select

        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.tts_usage import TTSUsage
        from app.services.tts.usage import record_synthesis

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def _count() -> int:
            async with AsyncSessionFactory() as db:
                return int(
                    await db.scalar(
                        select(func.count())
                        .select_from(TTSUsage)
                        .where(TTSUsage.speaker == "OffSwitch")
                    )
                    or 0
                )

        monkeypatch.setattr(settings, "TTS_USAGE_LEDGER_ENABLED", False)
        await record_synthesis(
            provider="fish",
            model="s1",
            speaker="OffSwitch",
            characters=10,
            cost_usd=0.001,
            cached=False,
            user_id=None,
        )
        assert await _count() == 0

    def test_both_paths_of_the_speak_endpoint_record(self):
        """
        A SOURCE ASSERTION, because the failure it catches is a line somebody DELETES. The
        cache-hit path is the one at risk: it returns early and looks like it has nothing to
        record, and it is the path whose rows carry the number that matters most — the
        characters the audio cache avoided paying for.
        """
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app"
            / "api"
            / "v1"
            / "tts.py"
        ).read_text()
        # FOUR, NOT TWO, BECAUSE THERE ARE NOW TWO ENDPOINTS. `/tts/speak` and
        # `/tts/speak/stream` each have a cache-hit path and a paid-synthesis path, and all
        # four record. The count went up because the endpoint was added, and it must never go
        # DOWN — a streaming path that recorded nothing would be speech spend the margin sheet
        # cannot see, which is the same hole this test was written to close for the first one.
        assert source.count("await record_synthesis(") == 4, (
            "every path of BOTH speak endpoints — cache hit and paid synthesis — must record; "
            "a ledger of misses alone can measure the bill and never measure what reduces it"
        )
        assert "cached=True" in source
        assert "cached=False" in source

    def test_the_redis_brake_was_not_replaced_by_the_ledger(self):
        """
        TWO WRITES, TWO PURPOSES. `record_tts_spend` is the budget brake read by
        `_budget_room` before every synthesis, and it deliberately has no database
        dependency — a money guard that fails open when Postgres is slow is a money guard
        that does not exist. Somebody tidying up "the duplicate" would remove the cap.
        """
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app"
            / "api"
            / "v1"
            / "tts.py"
        ).read_text()
        assert "await record_tts_spend(" in source
        assert "tts_spend_today()" in source
