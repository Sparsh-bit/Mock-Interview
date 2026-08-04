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

import pytest

from app.services.ai.vector_cache import (
    CACHEABLE_FEATURES,
    UncacheableFeature,
    _SIMILARITY_THRESHOLD,
    embed,
    key_hash,
    normalize_key,
)
from app.models.ai_cache import EMBEDDING_DIM


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
        assert CACHEABLE_FEATURES == frozenset({"gd_topic_prep", "interview_plan"})

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
        import re

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
