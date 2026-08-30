"""
Consent, disclosure, and erasure that is lawful rather than merely thorough.

THREE THINGS ARE UNDER TEST, and the third is the one that had a real bug.

  1. Consent is recorded as an append-only ledger, so withdrawal is a new row and
     the history survives — because the history is the evidence that the processing
     which ALREADY happened was lawful when it happened.
  2. The §5/§16 disclosure is derived from this deployment's own configuration. A
     hardcoded list is correct on the day it is written and wrong the first time
     somebody flips AI_PROVIDER, and a notice naming the wrong country is worse than
     none because it is a statement the candidate relied on.
  3. Erasure keeps what the law requires it to keep. `POST /users/me/delete` used to
     cascade `credit_events` and `offer_redemptions` away. Those are books of
     account: Companies Act §128(5) wants eight financial years, and DPDP §8(7) makes
     erasure yield to a retention obligation under another law. The old behaviour
     destroyed them silently, on a path a user triggers themselves.

The deletion tests care as much about what SURVIVES as about what goes, and about
the survivors no longer naming anybody. Retaining a financial row that still carries
the person's id is a rename of the problem, not a fix.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import func, select

from app.core.config import settings
from app.main import app


def _token(user_id: uuid.UUID, email: str) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": email,
            "aud": settings.SUPABASE_JWT_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )


async def _client():
    return ASGITransport(app=app, raise_app_exceptions=False)


# ── The disclosure ───────────────────────────────────────────────────────────


class TestTheDisclosureDescribesThisDeployment:
    def test_it_names_the_provider_this_deployment_actually_uses(self, monkeypatch):
        """
        Flip the provider; the disclosure follows. This is the whole reason it is
        derived rather than written out — the previous hardcoded list called ZhipuAI
        the "standby" while AI_PROVIDER defaulted to glm, i.e. every resume went to
        China first and the notice said otherwise.
        """
        from app.services.legal import disclosure as d

        monkeypatch.setattr(settings, "AI_PROVIDER", "glm")
        monkeypatch.setattr(settings, "AI_FALLBACK_PROVIDER", "nvidia")
        names = [p.name for p in d.active_processors()]
        assert "ZhipuAI (GLM)" in names
        assert "Anthropic" not in names

        monkeypatch.setattr(settings, "AI_PROVIDER", "anthropic")
        names = [p.name for p in d.active_processors()]
        assert "Anthropic" in names

    def test_it_names_the_country_for_every_processor(self):
        # §16 is about destinations. A processor with no country is not a disclosure.
        from app.services.legal.disclosure import active_processors

        for p in active_processors():
            assert p.country.strip(), f"{p.name} has no country"
            assert p.receives.strip(), f"{p.name} does not say what it receives"
            assert p.purpose.strip(), f"{p.name} does not say why"

    def test_china_is_named_rather_than_softened(self, monkeypatch):
        """
        docs/COMPLIANCE.md calls this the sharpest §16 exposure: DPDP permits transfer
        except to countries the Government restricts, the list is not yet notified,
        and it may include China. Whatever the business decides, the candidate is told.
        """
        from app.services.legal.disclosure import _CATALOGUE

        assert _CATALOGUE["glm"].country == "China"

    def test_every_provider_the_factory_accepts_has_an_entry(self):
        """
        THE GUARD AGAINST THE DISCLOSURE GOING QUIETLY STALE. Adding a provider to the
        factory without adding it here means a deployment can send resumes to a
        service the notice does not mention — and `active_processors` skips unknown
        keys rather than inventing a country, so nothing would fail at runtime.
        """
        from pathlib import Path

        from app.services.ai import provider_factory
        from app.services.legal.disclosure import _CATALOGUE

        source = Path(provider_factory.__file__ or "").read_text()
        for key in ("anthropic", "glm", "nvidia"):
            if f'"{key}"' in source or f"'{key}'" in source:
                assert key in _CATALOGUE, (
                    f"provider_factory can build {key!r} but the privacy disclosure "
                    f"has no entry for it — resumes would go somewhere unnamed"
                )

    def test_the_draft_flag_is_part_of_the_payload(self):
        # So the UI cannot render this text without also showing it is not a
        # lawyer-reviewed policy. A comment in the source cannot do that.
        from app.services.legal.disclosure import disclosure

        assert disclosure()["draft"] is True

    def test_no_grievance_contact_is_invented_when_none_is_configured(self, monkeypatch):
        """
        An obvious gap beats a plausible fabrication. A made-up name in a compliance
        notice looks like the obligation was discharged.
        """
        from app.services.legal.disclosure import disclosure

        monkeypatch.setattr(settings, "DPO_NAME", "")
        monkeypatch.setattr(settings, "DPO_EMAIL", "")
        grievance = disclosure()["grievance"]
        assert grievance["configured"] is False
        assert not grievance["name"]

        monkeypatch.setattr(settings, "DPO_NAME", "A. Person")
        monkeypatch.setattr(settings, "DPO_EMAIL", "grievance@example.test")
        assert disclosure()["grievance"]["configured"] is True


@pytest.mark.asyncio
class TestTheNoticeIsReadableBeforeSigningUp:
    async def test_disclosure_needs_no_token(self):
        """
        §5 requires notice BEFORE processing, which is before there is an account to
        authenticate. A notice you must sign up to read is not notice.
        """
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=await _client(), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            r = await ac.get("/api/v1/legal/disclosure")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["processors"]
        assert body["draft"] is True
        assert "notice_version" in body


# ── Consent ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestConsent:
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
                    email=f"consent-{uid}@example.test",
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
                transport=await _client(), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            return await ac.post(
                f"/api/v1/legal{path}",
                json=body,
                headers={"Authorization": f"Bearer {_token(uid, 'c@example.test')}"},
            )

    async def _get(self, uid: uuid.UUID, path: str):
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=await _client(), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            return await ac.get(
                f"/api/v1/legal{path}",
                headers={"Authorization": f"Bearer {_token(uid, 'c@example.test')}"},
            )

    async def test_signup_records_all_three_answers_with_a_timestamp(self, user):
        r = await self._post(
            user,
            "/consent/signup",
            {"privacy_notice": True, "terms": True, "age_18_plus": True},
        )
        assert r.status_code == 201, r.text

        got = (await self._get(user, "/consent")).json()["consents"]
        by_purpose = {c["purpose"]: c for c in got}
        for purpose in ("privacy_notice", "terms", "age_18_plus"):
            assert by_purpose[purpose]["granted"] is True
            # Timestamped and version-stamped: consent you cannot evidence is consent
            # you do not have.
            assert by_purpose[purpose]["at"]
            assert by_purpose[purpose]["notice_version"]
            assert by_purpose[purpose]["source"] == "signup"

    async def test_declaring_under_18_is_refused_rather_than_recorded(self, user):
        """
        §9 prohibits behavioural monitoring of children outright, and this product
        measures speech pace, fillers, pauses and presence. There is no version of the
        product that may run for a self-declared under-18, so this is a refusal, not a
        flag to be handled later.
        """
        r = await self._post(
            user,
            "/consent/signup",
            {"privacy_notice": True, "terms": True, "age_18_plus": False},
        )
        assert r.status_code == 403
        assert "18" in r.text

    async def test_a_refusal_of_the_terms_is_recorded_rather_than_refused(self, user):
        # "They declined" is a fact worth holding. Only the age answer is a hard stop.
        r = await self._post(
            user,
            "/consent/signup",
            {"privacy_notice": True, "terms": False, "age_18_plus": True},
        )
        assert r.status_code == 201
        got = {c["purpose"]: c for c in (await self._get(user, "/consent")).json()["consents"]}
        assert got["terms"]["granted"] is False

    async def test_a_purpose_never_asked_is_null_not_false(self, user):
        """
        "We never asked you" and "you said no" are different answers, and a UI that
        cannot tell them apart will either nag somebody who declined or silently treat
        silence as agreement.
        """
        got = {c["purpose"]: c for c in (await self._get(user, "/consent")).json()["consents"]}
        assert got["resume_processing"]["granted"] is None

    async def test_withdrawal_appends_and_wins(self, user):
        """
        §6(4)–(6): withdrawal as easy as giving. And the grant must SURVIVE it — the
        history is the evidence that what was processed beforehand was lawful.
        """
        from app.db.session import AsyncSessionFactory
        from app.models.consent import ConsentEvent

        await self._post(
            user, "/consent", {"purpose": "resume_processing", "granted": True}
        )
        await self._post(
            user, "/consent", {"purpose": "resume_processing", "granted": False}
        )

        got = {c["purpose"]: c for c in (await self._get(user, "/consent")).json()["consents"]}
        assert got["resume_processing"]["granted"] is False, "the newest answer must win"

        async with AsyncSessionFactory() as db:
            rows = await db.scalar(
                select(func.count())
                .select_from(ConsentEvent)
                .where(
                    ConsentEvent.user_id == user,
                    ConsentEvent.purpose == "resume_processing",
                )
            )
        assert rows == 2, "withdrawal overwrote the grant instead of appending to it"

    async def test_age_cannot_be_flipped_through_the_general_endpoint(self, user):
        r = await self._post(user, "/consent", {"purpose": "age_18_plus", "granted": False})
        assert r.status_code == 422

    async def test_an_unknown_purpose_is_refused(self, user):
        # A typo'd purpose is a consent record no query will ever find.
        r = await self._post(user, "/consent", {"purpose": "whatever", "granted": True})
        assert r.status_code == 422

    async def test_consent_is_scoped_by_the_token_with_no_user_id_parameter(self, user):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "legal.py").read_text()
        assert "user_id: uuid.UUID = Query" not in source
        assert "user_id" not in source.split("class SignupConsentRequest")[1].split("@router")[0]

    async def test_reading_your_consent_requires_a_token(self):
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=await _client(), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            r = await ac.get("/api/v1/legal/consent")
        assert r.status_code == 401


# ── The resume gate ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestTheResumeUploadIsGatedOnConsent:
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
                    email=f"up-{uid}@example.test",
                    is_active=True,
                    is_admin=False,
                )
            )
            await db.commit()
        return uid

    async def _upload(self, uid: uuid.UUID):
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=await _client(), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            return await ac.post(
                "/api/v1/resume/upload",
                files={"file": ("cv.pdf", b"%PDF-1.4 not really", "application/pdf")},
                headers={"Authorization": f"Bearer {_token(uid, 'u@example.test')}"},
            )

    async def test_upload_without_consent_is_428_not_403(self, user):
        """
        428 PRECONDITION REQUIRED so the client can tell "do this first" from "you may
        not", and open the disclosure rather than showing a dead end.
        """
        r = await self._upload(user)
        assert r.status_code == 428, r.text
        assert r.json()["detail"]["purpose"] == "resume_processing"

    async def test_the_gate_is_the_first_thing_the_handler_does(self, user):
        """
        BEFORE THE FILE IS EVEN VALIDATED. A 415 for the wrong MIME type would mean the
        bytes were read and inspected before anybody was told where they go.
        """
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=await _client(), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            r = await ac.post(
                "/api/v1/resume/upload",
                files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
                headers={"Authorization": f"Bearer {_token(user, 'u@example.test')}"},
            )
        assert r.status_code == 428, "the file was inspected before consent was checked"

    async def test_withdrawing_consent_closes_the_gate_again(self, user):
        from app.db.session import AsyncSessionFactory
        from app.models.consent import PURPOSE_RESUME_PROCESSING, SOURCE_SETTINGS
        from app.services.legal.consent import record

        async with AsyncSessionFactory() as db:
            await record(
                db, user, purpose=PURPOSE_RESUME_PROCESSING,
                granted=True, source=SOURCE_SETTINGS,
            )
            await db.commit()
        # Consent granted: the gate lets it through and it fails on the file instead.
        assert (await self._upload(user)).status_code != 428

        async with AsyncSessionFactory() as db:
            await record(
                db, user, purpose=PURPOSE_RESUME_PROCESSING,
                granted=False, source=SOURCE_SETTINGS,
            )
            await db.commit()
        assert (await self._upload(user)).status_code == 428


# ── Erasure, and what it may not erase ───────────────────────────────────────


@pytest.mark.asyncio
class TestDeletionRespectsRetention:
    @pytest.fixture
    async def paying_user(self):
        """An account with the three things that must survive and several that must not."""
        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base
        from app.models.billing import CreditEvent, Offer, OfferRedemption
        from app.models.company import Company, InterviewTrack
        from app.models.consent import PURPOSE_TERMS, SOURCE_SIGNUP
        from app.models.report import Report
        from app.models.session import InterviewSession, SessionStatus
        from app.models.user import Profile, User
        from app.services.legal.consent import record

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        uid = uuid.uuid4()
        email = f"pay-{uid}@example.test"
        session_id = uuid.uuid4()
        offer_id = uuid.uuid4()
        # UNIQUE PER TEST. The fixture is function-scoped but the database is not
        # truncated between tests in this class, and a shared literal made the
        # retained-row query match a PREVIOUS test's user — which reads as a digest
        # mismatch and sends you looking at the hashing.
        payment_ref = f"pay_{uuid.uuid4().hex[:12]}"

        async with AsyncSessionFactory() as db:
            company = Company(id=uuid.uuid4(), name="C", slug=f"c-{uuid.uuid4().hex[:8]}")
            track = InterviewTrack(
                id=uuid.uuid4(), company_id=company.id, name="T",
                slug=f"t-{uuid.uuid4().hex[:8]}",
            )
            db.add_all([
                company, track,
                User(id=uid, supabase_uid=str(uid), email=email,
                     is_active=True, is_admin=False),
                Offer(id=offer_id, code=f"CODE{uuid.uuid4().hex[:6].upper()}",
                      label="Test offer", kind="flat", value=10000,
                      applies_to=["interview"], enabled=True),
            ])
            await db.flush()
            db.add_all([
                Profile(user_id=uid, full_name="Pays Money", timezone="UTC"),
                InterviewSession(id=session_id, user_id=uid, track_id=track.id,
                                 status=SessionStatus.COMPLETED),
                CreditEvent(user_id=uid, feature="interview", kind="purchase", delta=3,
                            payment_ref=payment_ref,
                            created_at=datetime.now(UTC)),
                OfferRedemption(offer_id=offer_id, user_id=uid, item_id="interview",
                                original_paise=19900, charged_paise=9900,
                                payment_ref=payment_ref,
                                created_at=datetime.now(UTC)),
            ])
            await db.flush()
            db.add(
                Report(session_id=session_id, user_id=uid, overall_score=71.0,
                       overall_score_label="Good", executive_summary="THE ASSESSMENT.",
                       readiness_level="close_to_ready", strengths=["a"], weaknesses=["b"],
                       topic_scores={}, improvement_roadmap=[],
                       raw_report={"generated_by": "ai"})
            )
            await record(db, uid, purpose=PURPOSE_TERMS, granted=True, source=SOURCE_SIGNUP)
            await db.commit()
        return {"uid": uid, "email": email, "offer_id": offer_id, "ref": payment_ref}

    async def _delete(self, uid: uuid.UUID, email: str, confirm: str):
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=await _client(), base_url="http://test", timeout=30.0
            ) as ac,
        ):
            return await ac.post(
                "/api/v1/users/me/delete",
                json={"confirm_email": confirm},
                headers={"Authorization": f"Bearer {_token(uid, email)}"},
            )

    async def test_the_financial_ledger_survives_the_account(self, paying_user, monkeypatch):
        """
        THE BUG THIS FILE EXISTS FOR. `credit_events` was ON DELETE CASCADE, so a person
        exercising their erasure right destroyed the books of account with it —
        silently, and on a path they trigger themselves. Companies Act §128(5) wants
        eight financial years; DPDP §8(7) makes erasure yield to that.
        """
        from app.api.v1 import admin as admin_api
        from app.db.session import AsyncSessionFactory
        from app.models.billing import CreditEvent, OfferRedemption

        monkeypatch.setattr(admin_api, "_delete_supabase_user", _ok)
        monkeypatch.setattr(admin_api, "_delete_stored_files", _no_files)

        r = await self._delete(paying_user["uid"], paying_user["email"], paying_user["email"])
        assert r.status_code == 200, r.text

        async with AsyncSessionFactory() as db:
            credits = (
                await db.execute(
                    select(CreditEvent).where(CreditEvent.payment_ref == paying_user["ref"])
                )
            ).scalars().all()
            redemptions = (
                await db.execute(
                    select(OfferRedemption).where(
                        OfferRedemption.offer_id == paying_user["offer_id"]
                    )
                )
            ).scalars().all()

        assert credits, "the credit ledger was destroyed by an erasure request"
        assert redemptions, "the offer redemption was destroyed by an erasure request"
        # The amounts are what the Companies Act is asking for, and they are intact.
        assert credits[0].delta == 3
        assert redemptions[0].charged_paise == 9900

    async def test_the_survivors_no_longer_name_anybody(self, paying_user, monkeypatch):
        """
        Keeping a financial row that still carries the user id is a rename of the
        problem, not erasure. The identity goes; a salted one-way digest takes its
        place so the surviving rows stay reconcilable with each other and with nobody.
        """
        from app.api.v1 import admin as admin_api
        from app.db.session import AsyncSessionFactory
        from app.models.billing import CreditEvent
        from app.services.legal.retention import subject_digest

        monkeypatch.setattr(admin_api, "_delete_supabase_user", _ok)
        monkeypatch.setattr(admin_api, "_delete_stored_files", _no_files)
        await self._delete(paying_user["uid"], paying_user["email"], paying_user["email"])

        async with AsyncSessionFactory() as db:
            row = await db.scalar(
                select(CreditEvent).where(CreditEvent.payment_ref == paying_user["ref"])
            )
            await db.refresh(row, ["retained_subject"])

        assert row.user_id is None, "the retained row still names the deleted account"
        assert row.retained_subject == subject_digest(paying_user["uid"])
        # One-way: the digest must not be the id, nor contain it.
        assert str(paying_user["uid"]) not in row.retained_subject

    async def test_the_sensitive_data_really_is_gone(self, paying_user, monkeypatch):
        """
        The other half, and the more important one. Retention is not an excuse to keep
        the assessment, the answers or the resume — none of those has a statutory
        retention, and they are the sensitive data.
        """
        from app.api.v1 import admin as admin_api
        from app.db.session import AsyncSessionFactory
        from app.models.report import Report
        from app.models.session import InterviewSession
        from app.models.user import Profile, User

        monkeypatch.setattr(admin_api, "_delete_supabase_user", _ok)
        monkeypatch.setattr(admin_api, "_delete_stored_files", _no_files)
        await self._delete(paying_user["uid"], paying_user["email"], paying_user["email"])

        async with AsyncSessionFactory() as db:
            assert await db.scalar(select(User).where(User.id == paying_user["uid"])) is None
            assert (
                await db.scalar(select(Profile).where(Profile.user_id == paying_user["uid"]))
                is None
            )
            assert (
                await db.scalar(
                    select(InterviewSession).where(
                        InterviewSession.user_id == paying_user["uid"]
                    )
                )
                is None
            )
            assert (
                await db.scalar(select(Report).where(Report.user_id == paying_user["uid"]))
                is None
            )

    async def test_the_user_is_told_what_was_kept(self, paying_user, monkeypatch):
        # Somebody exercising an erasure right is entitled to know the financial
        # records do not go, and why. Logging it is not telling them.
        from app.api.v1 import admin as admin_api

        monkeypatch.setattr(admin_api, "_delete_supabase_user", _ok)
        monkeypatch.setattr(admin_api, "_delete_stored_files", _no_files)

        body = (
            await self._delete(
                paying_user["uid"], paying_user["email"], paying_user["email"]
            )
        ).json()
        assert body["retained_deidentified"]["credit_events"] == 1
        assert "8 years" in body["retention_note"]

    async def test_a_wrong_confirmation_still_deletes_nothing(self, paying_user):
        from app.db.session import AsyncSessionFactory
        from app.models.user import User

        r = await self._delete(
            paying_user["uid"], paying_user["email"], "not-my-email@example.test"
        )
        assert r.status_code == 400
        async with AsyncSessionFactory() as db:
            assert await db.scalar(select(User).where(User.id == paying_user["uid"])) is not None

    def test_the_digest_is_salted(self):
        """
        An unsalted digest of a UUID is reversible by anyone holding the id — an old
        export, a stale log line — which would make the pseudonymisation decorative.
        """
        import hashlib

        from app.services.legal.retention import subject_digest

        uid = uuid.uuid4()
        assert subject_digest(uid) != hashlib.sha256(str(uid).encode()).hexdigest()
        # Stable for the same id, so the retained rows stay joinable to each other.
        assert subject_digest(uid) == subject_digest(uid)


async def _ok(*args, **kwargs) -> bool:
    """Stands in for the Supabase auth-admin call, which needs a live project."""
    return True


async def _no_files(*args, **kwargs) -> int:
    """Stands in for storage deletion, which needs a live bucket."""
    return 0
