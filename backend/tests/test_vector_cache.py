"""
The pgvector cache — tests/test_vector_cache.py

The cache exists to cut the AI bill, and the way a cache like this fails is not by
being slow. It fails by serving the WRONG entry: the ideal answer to a different
question, or worse, content generated from another candidate's answers. Either is worse
than paying for the generation, so most of what follows tests what must NOT match.

These tests are pure — no database — because the matching logic is where every decision
lives. The database round-trip, the HNSW index and the hit counting are exercised
separately against real pgvector (see tests/test_vector_cache_db.py).
"""

import re

import pytest

from app.models.ai_cache import EMBEDDING_DIM
from app.services.ai.vector_cache import (
    _SIMILARITY_THRESHOLD,
    CACHEABLE_FEATURES,
    UncacheableFeature,
    embed,
    key_hash,
    normalize_key,
)


def cos(a: str, b: str) -> float:
    return sum(x * y for x, y in zip(embed(a), embed(b), strict=True))


def matches(a: str, b: str) -> bool:
    """The full decision the cache makes: exact hash, else vector near-match."""
    return key_hash(a) == key_hash(b) or cos(a, b) >= _SIMILARITY_THRESHOLD


class TestTheTenancyAllowlist:
    """
    The one rule that is not a performance question. This app has already shipped a bug
    that quoted one candidate's words at another; migration 010 exists because of it.
    """

    def test_nothing_derived_from_a_candidate_answer_is_cacheable(self):
        # Each of these is generated FROM what a specific person said. Caching any of
        # them across users is the same class of defect as that bug.
        for feature in (
            "cross_question",
            "report_generation",
            "gd_evaluation",
            "communication_evaluation",
            "communication_cross_question",
            "code_analysis",
            "gd_panel_turn",
            "resume_analysis",
            # The trap. prompts/model_answer.md takes $candidate_answer and writes the
            # ideal answer "judged against what the candidate actually said", so the
            # output quotes one person's words. It is already cached per-answer on
            # answers.model_answer, which is the right scope; caching it globally would
            # hand candidate B a critique of candidate A's answer.
            "model_answer",
        ):
            assert feature not in CACHEABLE_FEATURES, (
                f"{feature} is generated from a candidate's own input and must never be "
                "shared between users"
            )

    def test_the_allowlist_holds_only_public_topic_data(self):
        """
        Pinned as an exact set, not a subset check, so a new entry cannot be added without
        editing this line — which is the moment somebody has to say out loud why the new
        feature's input is public.

        `study_resources`: the key is a TOPIC LABEL from the question bank ("Spring
        Security", "Collections"), the same string for every candidate. Nothing the
        candidate said reaches either the key or the prompt — the generation is handed the
        topic name and nothing else. It is the purest entry on this list, and unlike the
        others its key space is bounded by the syllabus rather than by the user count, so
        it saturates and stops costing anything at all.

        `question_bank`: a pool of interview questions for one (role, difficulty, topic list).
        The key is three pieces of SYLLABUS — a track name, a difficulty band, and the topic
        names configured for that track. The generation that fills it is handed exactly those
        and is told in the prompt that the questions must not depend on any particular
        candidate: no resume, no previous answer, no focus concepts.

        `quiz_pool`: a pool of quiz questions for one (track, company, topic set). The key is
        those three, and they are the WHOLE of the generation prompt — api/v1/quiz.py hands
        `builder.chat` exactly `track_name`, `topics`, `count` and `company` and nothing else.
        No resume, no answer, no name, no typed focus. `count` is deliberately not in the key
        because it does not change what a question IS, only how many are asked for.

        It stores a POOL rather than a quiz, and that is what resolves the objection recorded
        against caching quizzes at all (see the note on `gd_topic_prep`): a cached QUIZ would
        serve the same questions back to everybody and to the same candidate on a retake, while
        a pool is drawn from at random, so cost falls without freshness going with it.

        A row is re-validated on load against `_PickedQuestion` before use — rows outlive
        deploys, and a row from an older shape would reach a candidate as a broken quiz rather
        than as an error anybody sees.

        The safety rests on the branch that reaches it. `_generate_question` consults this
        pool ONLY when `focus_concepts` is empty — the moment the interview has something
        specific to probe, that question is ABOUT this candidate and goes through the uncached
        path instead. A question derived from somebody's missed concepts is never shared, and
        that is enforced by control flow rather than by hoping the key stays clean.

        Like study_resources, its key space is the syllabus rather than the user count, so it
        saturates: once each (role, difficulty) cell is filled it costs nothing forever.
        """
        assert (
            frozenset({"gd_topic_prep", "study_resources", "question_bank", "quiz_pool"})
            == CACHEABLE_FEATURES
        )

    def test_the_plan_is_not_globally_cacheable_because_it_reads_the_resume(self):
        """
        `interview_plan` used to be on the allowlist as "company + program + focus". That
        described the KEY, not the prompt: interview_plan.md interpolates $resume and is told
        to include questions referencing the candidate's own projects by name, so a global
        cache would serve candidate B a question about candidate A's internship.

        Nothing leaked, because no caller ever wired it — which is the worse failure, not the
        better one. An unwired entry on a tenancy allowlist is a pre-approval waiting for
        somebody to act on it, and the resume is now a compulsory field.

        Asserted from the PROMPT AND THE BRIEF rather than left as a comment, so the entry
        cannot come back while the reason it was removed is still true. If the plan ever
        stops reading the resume, this test fails and the allowlist question can be reopened
        deliberately.

        THIS CHECKED `"$resume" in prompt` UNTIL THE PROMPT STOPPED HAVING VARIABLES.
        interview_plan.md is now loaded verbatim so it can be cached at the provider, and
        the resume moved into the user brief — so the old substring vanished while the
        tenancy hazard it guarded was completely unchanged. That is the dangerous direction
        for a test like this to break in: it would have gone green on a technicality and
        re-opened a global cache over candidate resumes.

        Both halves are checked now, which is stronger than the original: the prompt must
        still instruct the model to examine the resume, AND the brief must still carry it.
        """
        from pathlib import Path

        prompt = (
            Path(__file__).resolve().parents[1] / "app" / "prompts" / "interview_plan.md"
        ).read_text()
        assert "## The candidate's resume" in prompt, (
            "interview_plan.md no longer reads the resume — re-evaluate whether the plan is "
            "globally cacheable, deliberately, rather than assuming either answer"
        )
        assert "EVERY TECHNOLOGY NAMED ON A RESUME IS A CLAIM" in prompt

        from app.services.interview import orchestrator as orch

        brief = orch._plan_user_brief(
            company="Cognizant",
            program="Programmer Analyst",
            focus="",
            resume="Built a Spring Boot claims service at Acme.",
            business_context="(none)",
            research="(none)",
            already_asked="(none)",
            must_cover="(none)",
            question_mix="(none)",
            focus_directive="(none)",
            question_count=11,
        )
        assert "Spring Boot claims service" in brief, (
            "the resume no longer reaches the plan — the tenancy reason this entry was "
            "removed from the allowlist may no longer hold, and that is a decision to make "
            "deliberately rather than by a test quietly passing"
        )
        assert "interview_plan" not in CACHEABLE_FEATURES

    def test_the_shared_resource_generation_takes_only_a_topic(self):
        """
        The allowlist entry above is only safe while this stays true, so it is asserted
        rather than left to a docstring: if the resource generation ever grows a
        candidate-derived input, it must leave the allowlist.

        Asserted on the SIGNATURE and on what is interpolated into the prompt, not on
        whether the word "candidate" appears anywhere in the file. The prompt legitimately
        says "placement candidates" and "a candidate's evening" — that is prose describing
        who the resources are for, not a value read from one. A substring scan cannot tell
        those apart and would fail on correct code, which is how a guard gets deleted.
        """
        import inspect

        from app.services.prep import study_resources as sr

        # Only the session and the topic. No answer, session_id, user or transcript.
        assert list(inspect.signature(sr._generate).parameters) == ["db", "topic"]
        assert list(inspect.signature(sr.resolve).parameters) == ["db", "topic"]

        # And `topic` is the only thing interpolated into the messages.
        src = inspect.getsource(sr._generate)
        interpolations = re.findall(r"\{([a-z_]+)[^}]*\}", src)
        assert set(interpolations) <= {"topic"}, (
            f"the shared resource prompt interpolates {set(interpolations) - {'topic'}} — "
            "anything beyond the topic makes this per-candidate and uncacheable"
        )

    @pytest.mark.asyncio
    async def test_an_unlisted_feature_is_refused_at_runtime(self):
        # Enforced in code, not left to review — because the reviewer who adds the next
        # feature is the one who will not have read this file.
        from app.services.ai import vector_cache as vc

        # Both of these are generated from a candidate's own words. Passing None as the
        # session is deliberate: the guard must refuse BEFORE it ever touches the
        # database, so an unlisted feature cannot even attempt a read.
        with pytest.raises(UncacheableFeature):
            await vc.lookup(None, feature="cross_question", key="x")  # type: ignore[arg-type]
        with pytest.raises(UncacheableFeature):
            await vc.store(None, feature="model_answer", key="x", payload={})  # type: ignore[arg-type]


class TestWhatMustNotMatch:
    """False positives are the expensive failure. When in doubt, miss and pay."""

    def test_two_different_bank_questions_do_not_match(self):
        assert not matches(
            "Difference between HashMap and Hashtable",
            "Difference between ArrayList and LinkedList",
        )

    def test_a_narrower_question_does_not_match_a_broader_one(self):
        # "What is HashMap" has a different ideal answer from "HashMap vs Hashtable".
        assert not matches("Difference between HashMap and Hashtable", "What is HashMap")

    def test_overloading_does_not_match_overriding(self):
        # The pair most likely to collide: near-identical spelling, opposite meaning, and
        # confusing them is exactly the mistake candidates make. Character trigrams pull
        # these together, so this is the test that keeps the trigram weight honest.
        assert not matches("Explain method overloading", "Explain method overriding")

    def test_opposing_gd_topics_do_not_match(self):
        assert not matches(
            "Should AI replace teachers in schools",
            "Should schools ban mobile phones",
        )

    def test_an_empty_key_matches_nothing(self):
        # An all-zero vector has cosine 0 with everything, so an empty key must never be
        # served a hit — otherwise a bug upstream that passes "" would return whatever
        # happens to be nearest.
        assert not any(embed(""))
        assert not any(embed("   "))
        assert not matches("", "Difference between HashMap and Hashtable")


class TestWhatMustMatch:
    """The savings only exist if genuine restatements hit."""

    def test_word_order_and_connectives_do_not_matter(self):
        assert matches(
            "Difference between HashMap and Hashtable", "HashMap vs Hashtable difference"
        )

    def test_three_way_keyword_questions_match_regardless_of_phrasing(self):
        assert matches(
            "What is the difference between final, finally and finalize?",
            "final vs finally vs finalize",
        )

    def test_domain_abbreviations_fold_together(self):
        # Inherited from the plan cache's synonym map, which is where most of the real
        # matching power lives — placement jargon has many spellings for one thing.
        assert matches("Cognizant GenC Next Java FSE", "Cognizant Gen C Next Java Full Stack")

    def test_matching_ignores_case_and_punctuation(self):
        assert matches("EXPLAIN POLYMORPHISM!!", "explain polymorphism")

    def test_identical_keys_take_the_exact_path(self):
        # Not the vector path — one index probe instead of an ANN search, for the case
        # that is by far the most common.
        k = "Difference between HashMap and Hashtable"
        assert key_hash(k) == key_hash(k + "   ")


class TestTheVectorItself:
    def test_the_dimension_matches_the_column(self):
        # A mismatch here is a Postgres error on every insert. Loud, but only in
        # production if nothing asserts it.
        assert len(embed("anything at all")) == EMBEDDING_DIM

    def test_vectors_are_unit_length(self):
        # Cosine distance from the index is only meaningful if they are normalised.
        for key in ("HashMap", "Difference between final and finally", "AI in education"):
            norm = sum(v * v for v in embed(key)) ** 0.5
            assert abs(norm - 1.0) < 1e-9

    def test_embedding_is_stable_across_processes(self):
        # blake2b, not Python's hash(): hash() is salted per process by PYTHONHASHSEED,
        # so vectors written before a deploy would be meaningless after it and the hit
        # rate would silently fall to zero with no error anywhere. This asserts the
        # actual byte values rather than merely re-computing in-process.
        v = embed("HashMap")
        nonzero = [(i, round(x, 6)) for i, x in enumerate(v) if x]
        assert nonzero == [
            (188, 0.176777),
            (195, 0.176777),
            (262, 0.883883),
            (279, 0.176777),
            (341, 0.176777),
            (411, 0.176777),
            (447, 0.176777),
            (463, 0.176777),
        ], nonzero

    def test_normalisation_is_deterministic_and_sorted(self):
        assert normalize_key("Spring, Java") == normalize_key("Java, Spring")


class TestTheTestFixtureCannotDriftFromTheMigration:
    """
    tests/test_vector_cache_db.py builds ai_cache by hand, because the test database's
    schema comes from SQLAlchemy metadata and the `embedding vector(512)` column is
    created by migration 014 rather than by the model.

    A hand-written copy of a schema is a copy that drifts. If the migration gains a
    column and the fixture does not, those tests keep passing against a table that no
    longer resembles production — which is worse than not having them.
    """

    def test_the_fixture_and_the_migration_agree_on_the_columns(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[2]
        migration = (
            root / "database" / "migrations" / "versions" / "014_ai_vector_cache.py"
        ).read_text()
        fixture = (root / "backend" / "tests" / "test_vector_cache_db.py").read_text()

        # Column names the migration declares, from its sa.Column(...) calls plus the
        # vector column it adds with raw SQL.
        declared = set(re.findall(r'sa\.Column\(\s*\n?\s*"(\w+)"', migration))
        declared |= set(re.findall(r"ADD COLUMN (\w+) vector", migration))
        assert "embedding" in declared, "the migration should still add the vector column"

        # Bounded by the next statement rather than by the first ")" — which sits
        # inside gen_random_uuid() and truncated this to nothing.
        create = fixture.split("CREATE TABLE IF NOT EXISTS ai_cache (", 1)[1]
        create = create.split("CREATE INDEX", 1)[0]
        built = set(re.findall(r"^\s+(\w+)\s+\w", create, re.M))

        missing = sorted(declared - built)
        assert not missing, (
            "migration 014 declares columns the test fixture does not build: "
            f"{missing}. Update the CREATE TABLE in tests/test_vector_cache_db.py, or "
            "those tests are running against a table that no longer matches production."
        )

    def test_the_dimension_agrees_across_all_three_places(self):
        import pathlib

        from app.models.ai_cache import EMBEDDING_DIM

        root = pathlib.Path(__file__).resolve().parents[2]
        migration = (
            root / "database" / "migrations" / "versions" / "014_ai_vector_cache.py"
        ).read_text()
        fixture = (root / "backend" / "tests" / "test_vector_cache_db.py").read_text()

        # A mismatch is a Postgres error on every insert — loud, but only in whichever
        # environment happens to run first.
        assert f"_DIM = {EMBEDDING_DIM}" in migration
        assert f"vector({EMBEDDING_DIM})" in fixture
        assert len(embed("x")) == EMBEDDING_DIM
