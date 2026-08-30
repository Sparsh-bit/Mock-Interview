"""
Analytics is a consent purpose like any other — tests/test_analytics_consent.py

The frontend gate (`src/lib/analytics/core.test.ts`) proves nothing leaves the browser before
the answer is a grant. That is only worth anything if the server can actually hold the
answer, so this file pins the other half:

  * `analytics` is in the closed set of purposes, so a grant for it is recordable at all. A
    purpose outside `CONSENT_PURPOSES` is rejected with a 422, which would make the whole
    feature un-consentable — and the frontend would look correct while tracking nobody.
  * It is NULL until asked. "Never asked" and "said no" are different answers, and the gate
    reads `null` as denied — but the server must not conflate them, or nothing can ever tell
    whether a person was given the choice.
  * A signup that omits the field records a REFUSAL, not a grant. The frontend and backend
    deploy separately; a browser running yesterday's bundle sends no `analytics` key, and the
    only safe reading of silence is no.
  * Withdrawal works through the same endpoint as granting. §6(4) requires it to be as easy,
    and "as easy" in practice means the same call with a different boolean.
  * It is NOT a hard gate on anything. Refusing analytics must leave the product working
    identically — the moment a refusal costs a candidate a feature it stops being a free
    choice, which is the condition §6 puts on consent being consent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.core.config import settings
from app.main import app
from app.models.consent import (
    CONSENT_PURPOSES,
    PURPOSE_ANALYTICS,
    PURPOSE_RESUME_PROCESSING,
)


def _token(user_id: uuid.UUID) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": f"analytics-{user_id}@example.test",
            "aud": settings.SUPABASE_JWT_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


@pytest.mark.asyncio
class TestTheAnalyticsPurpose:
    @pytest.fixture
    async def user(self):
        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.user import User

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        uid = uuid.uuid4()
        async with AsyncSessionFactory() as db:
            db.add(
                User(
                    id=uid,
                    supabase_uid=str(uid),
                    email=f"analytics-{uid}@example.test",
                    is_active=True,
                    is_admin=False,
                )
            )
            await db.commit()
        return uid

    async def _post(self, uid: uuid.UUID, path: str, body: dict):
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            return await ac.post(
                f"/api/v1/legal{path}",
                json=body,
                headers={"Authorization": f"Bearer {_token(uid)}"},
            )

    async def _consents(self, uid: uuid.UUID) -> dict:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            res = await ac.get(
                "/api/v1/legal/consent",
                headers={"Authorization": f"Bearer {_token(uid)}"},
            )
        return {c["purpose"]: c for c in res.json()["consents"]}

    def test_it_is_in_the_closed_set_of_purposes(self):
        """
        `change_consent` 422s anything outside `CONSENT_PURPOSES`. Missing from that set, the
        settings toggle would fail for every user while the frontend looked entirely correct.
        """
        assert PURPOSE_ANALYTICS in CONSENT_PURPOSES

    def test_it_is_its_own_purpose_and_not_folded_into_the_privacy_notice(self):
        """
        §6 asks for consent that is SPECIFIC. "I have read what happens to my data" is not
        agreement to be measured by a third-party vendor — and bundling them would make every
        existing account look like it had already agreed to something nobody asked about.
        """
        assert PURPOSE_ANALYTICS != "privacy_notice"
        assert PURPOSE_ANALYTICS != PURPOSE_RESUME_PROCESSING

    async def test_it_is_null_until_the_question_is_put(self, user):
        got = await self._consents(user)
        assert got[PURPOSE_ANALYTICS]["granted"] is None, (
            "never asked must be distinguishable from refused — the gate reads null as "
            "denied, but the server has to know which it was"
        )

    async def test_a_signup_that_omits_the_field_records_a_refusal(self, user):
        """
        THE BACKWARD-COMPATIBILITY CASE, and the direction it fails in is what matters. The
        frontend and backend deploy separately, so a browser running the previous bundle will
        POST no `analytics` key. Defaulting to True would silently opt in every account that
        signed up during that window.
        """
        r = await self._post(
            user,
            "/consent/signup",
            {"privacy_notice": True, "terms": True, "age_18_plus": True},
        )
        assert r.status_code == 201, r.text
        got = await self._consents(user)
        assert got[PURPOSE_ANALYTICS]["granted"] is False

    async def test_ticking_it_at_signup_records_a_grant_with_its_evidence(self, user):
        r = await self._post(
            user,
            "/consent/signup",
            {
                "privacy_notice": True,
                "terms": True,
                "age_18_plus": True,
                "analytics": True,
            },
        )
        assert r.status_code == 201, r.text
        row = (await self._consents(user))[PURPOSE_ANALYTICS]
        assert row["granted"] is True
        # Consent you cannot evidence is consent you do not have.
        assert row["at"]
        assert row["notice_version"]
        assert row["source"] == "signup"

    async def test_declining_it_at_signup_still_creates_the_account(self, user):
        """
        THE PROPERTY THAT MAKES IT A REAL CHOICE. Unlike the age declaration, a refusal here
        is recorded and the signup succeeds — a consent that costs you the product is not
        freely given, which is the condition §6 puts on it being consent.
        """
        r = await self._post(
            user,
            "/consent/signup",
            {
                "privacy_notice": True,
                "terms": True,
                "age_18_plus": True,
                "analytics": False,
            },
        )
        assert r.status_code == 201
        assert (await self._consents(user))[PURPOSE_ANALYTICS]["granted"] is False

    async def test_it_can_be_granted_and_withdrawn_through_the_same_endpoint(self, user):
        """
        §6(4)–(6): withdrawal must be as easy as giving. The same call with a different
        boolean is the strongest form of "as easy" there is.
        """
        assert (
            await self._post(user, "/consent", {"purpose": "analytics", "granted": True})
        ).status_code == 201
        assert (await self._consents(user))[PURPOSE_ANALYTICS]["granted"] is True

        assert (
            await self._post(user, "/consent", {"purpose": "analytics", "granted": False})
        ).status_code == 201
        assert (await self._consents(user))[PURPOSE_ANALYTICS]["granted"] is False

    async def test_withdrawal_appends_rather_than_overwriting(self, user):
        """
        The history IS the evidence. Overwriting the grant would destroy the only proof that
        the measuring which already happened was lawful when it happened.
        """
        from sqlalchemy import func, select

        from app.db.session import AsyncSessionFactory
        from app.models.consent import ConsentEvent

        await self._post(user, "/consent", {"purpose": "analytics", "granted": True})
        await self._post(user, "/consent", {"purpose": "analytics", "granted": False})

        async with AsyncSessionFactory() as db:
            rows = int(
                await db.scalar(
                    select(func.count())
                    .select_from(ConsentEvent)
                    .where(
                        ConsentEvent.user_id == user,
                        ConsentEvent.purpose == PURPOSE_ANALYTICS,
                    )
                )
                or 0
            )
        assert rows == 2

    async def test_it_gates_nothing(self, user):
        """
        NO ENDPOINT MAY REQUIRE IT. `require_consent` is the gate mechanism, and analytics
        must never be one of its purposes — the moment refusing costs a candidate a feature,
        the choice is not free and the consent is not consent.

        A source assertion, because the failure it catches is a line somebody ADDS.
        """
        import pathlib

        api = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
        offenders = [
            str(path)
            for path in api.rglob("*.py")
            if "require_consent" in path.read_text()
            and "PURPOSE_ANALYTICS" in path.read_text()
            and "require_consent(db, current_user.user_id, PURPOSE_ANALYTICS"
            in path.read_text()
        ]
        assert offenders == [], (
            f"{offenders} gates a feature on the analytics consent. Refusing to be measured "
            "must never cost a candidate anything."
        )
