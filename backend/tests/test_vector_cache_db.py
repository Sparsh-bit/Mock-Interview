"""
The pgvector cache, against real pgvector — tests/test_vector_cache_db.py

Separate from test_vector_cache.py, which is pure. Everything here needs a Postgres with
the vector extension, because the parts being tested are the parts that only exist in the
database: the HNSW index and its operator class, the `<=>` distance operator, the
UPDATE ... RETURNING that counts a hit without a read-then-write race, and the scope
filter that keeps one user's entries away from another's.

None of that can be checked in Python. An HNSW index built for the wrong operator class,
for instance, is not an error — it is simply never used, and the only symptom is that
queries stay slow.

docker-compose now runs pgvector/pgvector:pg15 rather than postgres:15-alpine precisely so
these can run locally instead of only in production.
"""

import pytest
from sqlalchemy import text

from app.services.ai import vector_cache as vc

#: Skip rather than fail when there is no database. These are the only tests in the
#: suite that require one plus the vector extension, and CI runs lint and typecheck
#: only — a hard failure there would say "the cache is broken" when it means "there is
#: no Postgres here".
pytestmark = pytest.mark.asyncio


@pytest.fixture
async def clean_cache():
    """
    A session against the dev database, with the cache emptied.

    Self-contained rather than reusing test_integration.py's db_session: that fixture
    builds the whole schema from metadata, and the `embedding vector(512)` column is
    created by migration 014 rather than by the model — so a metadata-built schema has
    no vector column and every one of these tests would fail for the wrong reason.
    """
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import AsyncSessionFactory

    try:
        async with AsyncSessionFactory() as db:
            # Build exactly what migration 014 builds, idempotently. The test suite
            # points at its own database whose schema comes from SQLAlchemy metadata,
            # and the vector column is not in the model (see the note in
            # models/ai_cache.py) — so without this the table here would have no
            # embedding column and every near-match test would fail for the wrong
            # reason. Kept in step with 014 by test_vector_cache_schema below.
            await db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS ai_cache (
                        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                        created_at timestamptz NOT NULL DEFAULT now(),
                        feature varchar(64) NOT NULL,
                        cache_key varchar(500) NOT NULL,
                        key_hash varchar(64) NOT NULL,
                        scope varchar(64) NOT NULL DEFAULT 'global',
                        payload jsonb NOT NULL,
                        hit_count integer NOT NULL DEFAULT 0,
                        last_used_at timestamptz NOT NULL DEFAULT now(),
                        embedding vector(512),
                        CONSTRAINT uq_ai_cache_feature_key UNIQUE (feature, key_hash)
                    )
                    """
                )
            )
            # ADD COLUMN as well as CREATE TABLE, and this is not belt-and-braces.
            # test_integration.py's _setup_schema builds every table from SQLAlchemy
            # metadata, and ai_cache IS in the metadata — so when the full suite runs,
            # the table already exists WITHOUT the vector column and CREATE TABLE IF NOT
            # EXISTS silently does nothing. These tests then skipped rather than ran,
            # which is the worst outcome: a green suite covering none of this.
            await db.execute(
                text("ALTER TABLE ai_cache ADD COLUMN IF NOT EXISTS embedding vector(512)")
            )
            await db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_ai_cache_embedding ON ai_cache "
                    "USING hnsw (embedding vector_cosine_ops)"
                )
            )
            await db.execute(text("DELETE FROM ai_cache"))
            await db.commit()
            yield db
            await db.rollback()
    except (SQLAlchemyError, OSError) as exc:
        pytest.skip(f"needs Postgres with the vector extension: {exc}")


class TestRoundTrip:
    async def test_a_stored_generation_comes_back(self, clean_cache):
        db = clean_cache
        await vc.store(
            db,
            feature="gd_topic_prep",
            key="Difference between HashMap and Hashtable",
            payload={"answer": "HashMap is unsynchronised and permits one null key."},
        )
        await db.commit()

        got = await vc.lookup(
            db, feature="gd_topic_prep", key="Difference between HashMap and Hashtable"
        )
        assert got is not None
        assert got["answer"].startswith("HashMap is unsynchronised")

    async def test_a_restatement_of_the_same_question_hits(self, clean_cache):
        # The saving only exists if this works. Different wording, same ideal answer.
        db = clean_cache
        await vc.store(
            db,
            feature="gd_topic_prep",
            key="What is the difference between final, finally and finalize?",
            payload={"answer": "final is a modifier; finally always runs; finalize was a GC hook."},
        )
        await db.commit()

        got = await vc.lookup(db, feature="gd_topic_prep", key="final vs finally vs finalize")
        assert got is not None, "a restatement of a cached question must hit"

    async def test_a_different_question_does_not_hit(self, clean_cache):
        # The failure that matters: showing a candidate the ideal answer to something
        # they were not asked.
        db = clean_cache
        await vc.store(
            db,
            feature="gd_topic_prep",
            key="Difference between HashMap and Hashtable",
            payload={"answer": "..."},
        )
        await db.commit()

        assert (
            await vc.lookup(
                db, feature="gd_topic_prep", key="Difference between ArrayList and LinkedList"
            )
            is None
        )

    async def test_features_do_not_bleed_into_each_other(self, clean_cache):
        """
        One key, two features, and the second must not see the first.

        THIS TEST WAS BROKEN AND PASSING NOTHING. It used to ask for
        `feature="interview_plan"`, which is not in `CACHEABLE_FEATURES` — so `lookup`
        correctly RAISED on the allowlist guard instead of returning None, and the test
        errored rather than failing an assertion. It went unnoticed because it needs a live
        Postgres and CI runs only lint and typecheck (see CLAUDE.md), so nothing ever
        executed it.

        The behaviour it was reaching for is real and worth pinning, so it is now written
        against two features that are BOTH allowlisted. That is the case that could actually
        bleed: a quiz served a group-discussion motion because they hashed the same phrase.
        The allowlist guard is a different claim and gets its own test below.
        """
        db = clean_cache
        await vc.store(db, feature="gd_topic_prep", key="Should AI grade exams", payload={"n": 1})
        await db.commit()
        # Same key, different feature, both cacheable. A GD motion must never be served as
        # a bank question.
        assert await vc.lookup(db, feature="question_bank", key="Should AI grade exams") is None

    async def test_a_feature_outside_the_allowlist_is_refused_rather_than_missed(
        self, clean_cache
    ):
        """
        The guard the test above was accidentally exercising, asserted on purpose.

        `interview_plan` is not cacheable: a plan is built from the candidate's resume and
        the focus they typed, so serving one to somebody else is the exact tenancy failure
        migration 010 exists because of. The distinction that matters is REFUSED versus
        MISSED — a raise is a bug in the caller and has to be fixed; a None is a normal
        cache miss and would be silently ignored, which is how a non-cacheable feature ends
        up being cached anyway.
        """
        db = clean_cache
        with pytest.raises(ValueError, match="CACHEABLE_FEATURES"):
            await vc.lookup(db, feature="interview_plan", key="Should AI grade exams")
        with pytest.raises(ValueError, match="CACHEABLE_FEATURES"):
            await vc.store(db, feature="interview_plan", key="k", payload={"n": 1})


class TestTheUpdateOnEveryUse:
    """
    "Gets updated whenever anyone uses it" was an explicit requirement. It is also what
    makes the cache warm itself from real traffic instead of needing a seed job, and what
    gives LRU eviction something honest to sort on.
    """

    async def test_every_hit_is_counted(self, clean_cache):
        db = clean_cache
        key = "Difference between HashMap and Hashtable"
        await vc.store(db, feature="gd_topic_prep", key=key, payload={"answer": "..."})
        await db.commit()

        for _ in range(3):
            assert await vc.lookup(db, feature="gd_topic_prep", key=key) is not None
        await db.commit()

        hits = await db.scalar(text("SELECT hit_count FROM ai_cache WHERE feature='gd_topic_prep'"))
        assert hits == 3

    async def test_a_near_match_hit_is_counted_too(self, clean_cache):
        # The near path is a different SQL statement from the exact path, so it needs its
        # own assertion — an uncounted hit means the eviction order and the "is this cache
        # earning its keep" figure are both wrong.
        db = clean_cache
        await vc.store(
            db,
            feature="gd_topic_prep",
            key="What is the difference between final, finally and finalize?",
            payload={"answer": "..."},
        )
        await db.commit()

        assert await vc.lookup(db, feature="gd_topic_prep", key="final vs finally vs finalize")
        await db.commit()
        hits = await db.scalar(text("SELECT hit_count FROM ai_cache"))
        assert hits == 1

    async def test_last_used_moves_forward(self, clean_cache):
        db = clean_cache
        key = "Collections framework overview"
        await vc.store(db, feature="gd_topic_prep", key=key, payload={"a": 1})
        await db.commit()
        before = await db.scalar(text("SELECT last_used_at FROM ai_cache"))

        await vc.lookup(db, feature="gd_topic_prep", key=key)
        await db.commit()
        after = await db.scalar(text("SELECT last_used_at FROM ai_cache"))
        assert after >= before

    async def test_storing_the_same_key_twice_keeps_one_row(self, clean_cache):
        # Two concurrent requests for one key both generate — a cache cannot prevent that,
        # only a lock could, and a lock in front of a cache is a worse trade. What it must
        # do is not accumulate duplicate rows.
        db = clean_cache
        for answer in ("first", "second"):
            await vc.store(
                db, feature="gd_topic_prep", key="Explain polymorphism", payload={"a": answer}
            )
            await db.commit()

        rows = await db.scalar(text("SELECT count(*) FROM ai_cache"))
        assert rows == 1
        got = await vc.lookup(db, feature="gd_topic_prep", key="Explain polymorphism")
        assert got == {"a": "second"}, "the newer generation should win"


class TestScopeIsolation:
    async def test_a_scoped_entry_is_invisible_to_another_scope(self, clean_cache):
        # The mechanism that would let a per-user cache exist safely. Nothing uses it
        # today — everything on the allowlist is global — but the isolation has to be
        # proven before anything relies on it.
        db = clean_cache
        await vc.store(
            db, feature="gd_topic_prep", key="Threads hard", payload={"q": 1}, scope="user-A"
        )
        await db.commit()

        assert await vc.lookup(db, feature="gd_topic_prep", key="Threads hard", scope="user-A")
        assert (
            await vc.lookup(db, feature="gd_topic_prep", key="Threads hard", scope="user-B")
            is None
        )
        # And not visible to the global scope either.
        assert await vc.lookup(db, feature="gd_topic_prep", key="Threads hard") is None


class TestFailingSoft:
    async def test_a_lookup_on_a_broken_session_is_a_miss_not_an_error(self, clean_cache):
        # A cache that can fail a request is worse than no cache. This also covers
        # deploying the code before migration 014 has run: it costs money, it does not
        # break every feature that consults the cache.
        db = clean_cache
        await db.execute(text("DROP TABLE ai_cache"))
        assert await vc.lookup(db, feature="gd_topic_prep", key="anything") is None
        await db.rollback()


class TestEvictionAndStats:
    async def test_stats_report_hits_and_never_hit_entries(self, clean_cache):
        # A table full of hit_count=0 rows is the signal that caching a feature bought
        # nothing, which is the only honest way to decide whether to keep doing it.
        db = clean_cache
        await vc.store(db, feature="gd_topic_prep", key="Explain encapsulation", payload={"a": 1})
        await vc.store(db, feature="gd_topic_prep", key="Explain inheritance", payload={"a": 2})
        await db.commit()
        await vc.lookup(db, feature="gd_topic_prep", key="Explain encapsulation")
        await db.commit()

        rows = await vc.stats(db)
        entry = next(r for r in rows if r["feature"] == "gd_topic_prep")
        assert entry["entries"] == 2
        assert entry["hits"] == 1
        assert entry["never_hit"] == 1

    async def test_eviction_leaves_the_cache_intact_when_under_the_cap(self, clean_cache):
        db = clean_cache
        await vc.store(db, feature="gd_topic_prep", key="Explain abstraction", payload={"a": 1})
        await db.commit()
        assert await vc.evict_lru(db, feature="gd_topic_prep") == 0
        assert await db.scalar(text("SELECT count(*) FROM ai_cache")) == 1


class TestAFailedCacheStatementDoesNotKillTheRequest:
    """
    "the recent cognizant interview i gave the report was not able to get generated it is
    showing noting and error in genrating the report".

    THE MECHANISM, WHICH IS NOT WHAT THE CODE BELIEVED. Every public function in
    vector_cache.py caught `Exception` and degraded to a miss, and said so: "Never raises. A
    cache that can fail a request is worse than no cache." That was believed and it was
    false, because catching a Python exception does not un-abort a Postgres transaction. After
    any failed statement Postgres refuses every subsequent one on that connection:

        InFailedSQLTransactionError: current transaction is aborted,
        commands ignored until end of transaction block

    `get_db` opens ONE session per request and holds it for the whole request. So a single bad
    cache statement did not cost a cache miss — it killed every query that ran after it in
    that request. During report generation that is the report read, the scores, the persist
    and the commit. The candidate finishes an interview and gets an error and a blank page,
    and the log blames whichever innocent query happened to run next.

    `lookup`'s own comment claimed the opposite: that a missing migration "costs money rather
    than breaking every feature that consults the cache". Exactly backwards — it broke every
    such request outright, which is the widest blast radius from the smallest cause.

    THE TRIGGER USED HERE IS A REAL ONE. A wrong-width vector is what happens whenever
    `embed()` and the column's `vector(512)` disagree — a dimension change, a half-applied
    migration, an older row's function. Postgres rejects it, which is the honest behaviour;
    the bug was never the rejection, it was what the rejection took down with it.
    """

    async def test_the_caller_can_still_query_after_the_cache_fails(
        self, clean_cache, monkeypatch
    ):
        db = clean_cache

        # Work done BEFORE the cache call must survive it.
        await vc.store(db, feature="gd_topic_prep", key="before", payload={"n": 1})
        await db.commit()

        # Now make the next cache statement fail the way a real dimension mismatch does.
        monkeypatch.setattr(vc, "embed", lambda key: [0.1] * 8)

        # Must not raise — that contract held before and still holds.
        assert (
            await vc.lookup(db, feature="gd_topic_prep", key="anything at all") is None
        )

        # THE ASSERTION THAT WOULD HAVE CAUGHT IT. Before the savepoint this raised
        # InFailedSQLTransactionError, and in a real request every statement after the cache
        # call raised it too — which is what the candidate saw as "error generating the
        # report".
        survived = await db.execute(text("select 1"))
        assert survived.scalar() == 1

        # And the caller can still do real work, not merely a trivial select.
        assert await vc.lookup(db, feature="gd_topic_prep", key="before") is not None

    async def test_a_failed_store_does_not_take_the_request_with_it(
        self, clean_cache, monkeypatch
    ):
        db = clean_cache
        monkeypatch.setattr(vc, "embed", lambda key: [0.1] * 8)

        await vc.store(db, feature="question_bank", key="k", payload={"n": 1})

        survived = await db.execute(text("select 1"))
        assert survived.scalar() == 1

    async def test_work_committed_before_the_failure_is_not_rolled_back(
        self, clean_cache, monkeypatch
    ):
        """
        A savepoint rollback must undo the cache statement and nothing else. Rolling back the
        whole transaction would be a different way of losing the report — the candidate's
        answers would go with it.
        """
        db = clean_cache
        await vc.store(db, feature="gd_topic_prep", key="keep me", payload={"n": 7})
        await db.commit()

        monkeypatch.setattr(vc, "embed", lambda key: [0.1] * 8)
        await vc.lookup(db, feature="gd_topic_prep", key="whatever")

        monkeypatch.undo()
        kept = await vc.lookup(db, feature="gd_topic_prep", key="keep me")
        assert kept == {"n": 7}


class TestTheDifficultyBandsCannotReachEachOther:
    """
    "check if the vector databse is also working fine ... this is the only thing we have from
    which we can reduce the cost ... this must be the strongest part."

    It was working and it was serving the WRONG ROWS, which is worse than not working: a miss
    costs a generation, a wrong hit costs the candidate their interview escalation and looks
    like a saving.

    THE MEASUREMENT. `_bank_question` keyed its cache on
    `f"{track_name} | {difficulty} | {topics_str[:300]}"`. With the topic list that call site
    actually passes, the three difficulty variants of that string measure:

        worst pairwise similarity   0.9786
        _SIMILARITY_THRESHOLD       0.93

    One word in a hundred-odd tokens moves a cosine almost not at all. So the exact-hash path
    told the three keys apart while the ANN fallback matched whichever band was cached first,
    and a candidate escalating easy -> medium -> hard was served the same five questions back.
    Indistinguishable from repetition, and the reason escalation felt like it was not
    happening. `_persist_generated_question` then filed those questions under the REQUESTED
    difficulty, so a medium question was recorded as hard and fed the adaptive signal and the
    report.

    THE FIX IS THE SCOPE COLUMN, NOT THE THRESHOLD. `scope` is an indexed equality predicate
    in both the exact and the ANN query, so the bands cannot reach each other at any
    similarity. A threshold high enough to separate 0.9786 would also stop "Cognizant GenC"
    matching "cognizant gen-c" — which is the entire reason this cache is semantic rather than
    a hash table.

    These tests assert the SCOPING rather than the cosine. Asserting the cosine would re-pin
    the bug: the whole point is that the similarity no longer matters.
    """

    async def test_two_scopes_do_not_see_each_others_rows(self, clean_cache):
        db = clean_cache
        key = "Digital Nurture — Java FSE | OOP, Collections, Strings"
        await vc.store(db, feature="question_bank", key=key, payload={"band": "easy"},
                       scope="difficulty:easy")
        await db.commit()

        assert await vc.lookup(db, feature="question_bank", key=key,
                               scope="difficulty:easy") == {"band": "easy"}
        # THE ONE THAT WOULD HAVE CAUGHT IT.
        assert await vc.lookup(db, feature="question_bank", key=key,
                               scope="difficulty:hard") is None
        assert await vc.lookup(db, feature="question_bank", key=key,
                               scope="difficulty:medium") is None

    async def test_a_near_identical_key_still_matches_inside_one_scope(self, clean_cache):
        """
        The saving must survive the fix. Two spellings of the same setup should still share a
        row — that is what the cache is FOR, and scoping must not turn it into a hash table.
        """
        db = clean_cache
        await vc.store(db, feature="question_bank",
                       key="Cognizant GenC | OOP, Collections",
                       payload={"n": 1}, scope="difficulty:easy")
        await db.commit()
        hit = await vc.lookup(db, feature="question_bank",
                              key="cognizant gen-c | collections, OOP",
                              scope="difficulty:easy")
        assert hit == {"n": 1}

    async def test_the_orchestrator_passes_the_scope_at_both_call_sites(self):
        """
        Source assertion, because a lookup scoped and a store unscoped is the worst of both:
        every read misses, every write lands in the global scope, and the cache silently stops
        saving anything while appearing to work.
        """
        import inspect

        from app.services.interview.orchestrator import InterviewOrchestrator

        src = inspect.getsource(InterviewOrchestrator._bank_question)
        assert 'scope = f"difficulty:{difficulty}"' in src
        assert src.count("scope=scope") == 2
        # And the difficulty must be gone from the key, or the scoping buys nothing and the
        # key space is tripled twice over.
        assert '{track_name} | {difficulty} |' not in src
