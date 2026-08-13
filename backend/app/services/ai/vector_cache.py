"""
pgvector-backed cache for reusable AI generations — services/ai/vector_cache.py

The cheapest AI call is the one you never make. Measured at list price, one full
12-question interview costs about 23 cents and one 8-minute GD round about 36 cents, so
the AI bill is what decides whether this product can carry a thousand users.

Some generations are genuinely per-candidate and can never be reused. Several are not:
the ideal answer to "difference between HashMap and Hashtable" is the same for every
candidate asked it, the quiz for "Exception Handling / medium" is the same for
everybody, and candidates typing their own GD topic converge on the same dozen phrases.
This module serves those from Postgres instead of buying them again.

See migration 014 for the full design rationale. The three things worth knowing here:

WHY HASHED LEXICAL VECTORS, NOT A PAID EMBEDDINGS API. Anthropic sells no embeddings
endpoint, so real embeddings would mean a second provider — a new key, a new bill and,
worst of all, a new network call inside a CACHE LOOKUP, so the thing meant to remove
latency becomes a source of it. The keys being matched are 2-8 words of closed-domain
jargon, which is the shape hashed lexical features handle essentially as well as dense
embeddings. `embed()` below is the ONLY function that knows how a vector is built:
swapping in Voyage or OpenAI later is a change to that one function plus the dimension.

WHY POSTGRES, NOT THE EXISTING REDIS CACHE. semantic_cache.py already caches interview
plans in Redis and still does. This adds the two things Redis could not: entries that
survive a restart (cached output is too expensive to lose to an eviction), and an index,
so the cache can hold hundreds of per-question entries instead of a linearly-scanned
list capped at 200.

THE TENANCY RULE, WHICH IS ABSOLUTE. Only generations whose input is public topic-level
data may be cached globally. Anything derived from a candidate's own ANSWERS —
cross-questions, reports, GD or communication evaluations, code analysis — must never be
shared, no matter what it would save. This app has already shipped a bug that quoted one
candidate's words at another, and migration 010 exists because of it. `CACHEABLE_FEATURES`
below is the allowlist, and it is checked at runtime rather than trusted to review.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

import structlog
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_cache import EMBEDDING_DIM, GLOBAL_SCOPE
from app.services.ai.semantic_cache import _canonicalize

logger = structlog.get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Words carrying no discriminating signal in a QUESTION-shaped key.
#:
#: Layered on top of semantic_cache's _STOPWORDS rather than added to it. That list was
#: tuned for interview SETUPS — "Cognizant GenC Java FSE" — where a word like "between"
#: never appears. The keys here are question text, and its noise is different:
#: interrogatives, copulas and connectives. Adding these to the shared list would change
#: plan-cache matching for no reason.
#:
#: Aggressive on purpose. What discriminates one bank question from another is the
#: technical nouns, so "Difference between HashMap and Hashtable" and "HashMap vs
#: Hashtable" should reduce to the same key — they have the same ideal answer, and
#: paying twice for it is the whole thing this module exists to stop. Verified not to
#: over-merge: "What is HashMap" still reduces to {hashmap}, which is a different set
#: from {hashmap, hashtable} and misses, as it must.
_QUESTION_STOPWORDS = frozenset({
    "what", "which", "when", "where", "who", "whom", "whose", "how", "why",
    "is", "are", "was", "were", "be", "been", "am", "do", "does", "did",
    "can", "could", "would", "should", "will", "shall", "may", "might",
    "you", "your", "yours", "we", "us", "i", "me", "my", "it", "its", "they",
    "tell", "explain", "describe", "define", "definition", "discuss", "state",
    "give", "list", "mention", "write", "show", "compare", "contrast",
    "difference", "differences", "different", "between", "vs", "versus",
    "example", "examples", "briefly", "short", "please", "about", "mean",
    "means", "meaning", "used", "use", "uses", "using", "work", "works",
    "much", "many", "there", "that", "this", "these", "those", "from", "by",
    "at", "as", "into", "than", "then", "also", "if", "so",
})


#: Extra synonym folds for the phrases these keys actually contain.
#:
#: A separate layer from semantic_cache's _SYNONYMS for the same reason as the stopwords:
#: that map is about interview setups (company, program, role) and this is about topic
#: phrasing. Each entry here is a pair a candidate would consider the same subject and a
#: token-matcher would not — "Artificial Intelligence in education" missed a cached
#: "AI in education" until "artificial" and "intelligence" folded onto "ai".
#:
#: Multi-word phrases are handled by folding EACH word onto the same canonical token, so
#: "work from home" and "wfh" both reduce to {remotework} once "from" is dropped as a
#: stopword. That is cruder than phrase matching and it is enough here: these are
#: two-word compounds, not sentences.
_KEY_SYNONYMS: dict[str, str] = {
    "artificial": "ai",
    "intelligence": "ai",
    "ml": "ai",
    "chatgpt": "ai",
    "genai": "ai",
    "wfh": "remotework",
    "remote": "remotework",
    "home": "remotework",
    "office": "office",
    "onsite": "office",
    "socialmedia": "socialmedia",
    "social": "socialmedia",
    "media": "socialmedia",
    "school": "education",
    "schools": "education",
    "college": "education",
    "colleges": "education",
    "student": "education",
    "students": "education",
    "teacher": "education",
    "teachers": "education",
    "teaching": "education",
    "exam": "education",
    "exams": "education",
    "crypto": "cryptocurrency",
    "cryptocurrency": "cryptocurrency",
    "bitcoin": "cryptocurrency",
}


def _key_tokens(key: str) -> list[str]:
    """
    Canonical, discriminating tokens for a cache key.

    Runs the shared domain canonicalisation (synonym folding, "gen c" -> genc, the
    setup stopwords) and then drops question-shaped noise. Order is deliberate:
    canonicalisation may PRODUCE a token that then needs filtering.
    """
    tokens = _canonicalize(_TOKEN_RE.findall((key or "").lower()))
    folded = [_KEY_SYNONYMS.get(t, t) for t in tokens if t not in _QUESTION_STOPWORDS]
    # De-duplicate while keeping order. Folding collapses "artificial intelligence" to
    # two identical tokens, and counting "ai" twice would skew the vector toward it.
    return list(dict.fromkeys(folded))

#: Features whose output may be cached and shared across users.
#:
#: An allowlist, not a denylist, and checked at runtime — because the failure mode of
#: getting this wrong is not a slow page, it is serving one candidate content generated
#: from another candidate's answers. A new feature is uncacheable until somebody has
#: thought about it and added it here.
#:
#: Every entry must satisfy: the cache key and the generated output depend ONLY on
#: public data — a question from the bank, a topic name, a company or program, a
#: difficulty. If a candidate's own words are anywhere in the input, it does not belong.
#: NOT on this list, and worth spelling out because it is the trap: `model_answer`.
#: It LOOKS perfectly cacheable — the ideal answer to a fixed bank question should be
#: the same for everybody — and it is not. prompts/model_answer.md takes
#: $candidate_answer and $candidate_name, and the instruction is to write the ideal
#: answer "judged against what the candidate actually said". The output therefore
#: quotes and reacts to one person's words, so sharing it would hand candidate B a
#: critique of candidate A's answer. That is the same defect migration 010 exists to
#: prevent. It is already cached per-answer on answers.model_answer, which is the
#: correct scope for it. Making it globally cacheable would mean rewriting the prompt
#: to stop reading the candidate's answer at all — a product change, not a cache one.
#: REMOVED FROM THIS LIST, and the reason is the same defect wearing a third hat:
#: `interview_plan`. It was here as "company + program + focus", which was true of the key
#: but not of the PROMPT — prompts/interview_plan.md interpolates `$resume`, and is told to
#: include one or two questions that reference the candidate's own projects by name. A
#: global cache would therefore serve candidate B a question about candidate A's internship.
#: Nothing was actually leaking, because no caller ever wired this feature to the cache —
#: which is worse than it sounds rather than better: an unwired entry on an allowlist is a
#: standing invitation to wire it, and the next person to do so would have found a
#: pre-approved feature name and no warning. The resume became a COMPULSORY field, so the
#: window where this was merely theoretical is closed. The plan is still cached per-setup in
#: Redis, which is the correct scope for something shaped by one person's CV.
#: Also NOT on this list, for a different reason: `quiz_generation`. It is perfectly
#: tenancy-safe — prompts/quiz_generator.md reads only track, topics, count, company and
#: focus — but serving it from a shared cache would give every candidate on a topic the
#: identical quiz, and give a returning candidate the quiz they have already answered.
#: "I want different questions every time" is an explicit product requirement, and a
#: cache that quietly breaks it is not a saving. The version that WOULD work is a pool:
#: keep several variants per topic and serve one this candidate has not seen. That needs
#: per-user seen-tracking, so it is a feature, not a cache — deliberately not built here
#: rather than half-built.
CACHEABLE_FEATURES: frozenset[str] = frozenset(
    {
        # Turning a candidate-typed GD topic into a motion. The TOPIC is public — a
        # phrase like "AI in education", not something they said in a round — candidates
        # converge hard on the same handful, and unlike a quiz there is no reason to want
        # a DIFFERENT framing of the same motion next time.
        "gd_topic_prep",
        # Study resources for a topic. The purest case on this list: the key is a syllabus
        # LABEL from the question bank, identical for everybody, and nothing about the
        # candidate reaches the prompt. It is also the one whose key space is bounded by
        # the syllabus rather than by the user count, so it SATURATES — once every topic
        # anyone is weak in has been generated once, this feature costs nothing for every
        # future user. That is what makes cost per user fall as the user base grows.
        "study_resources",
    }
)

#: Cosine similarity at or above which two keys are "the same request".
#:
#: Higher than the plan cache's 0.82 on purpose. That cache matched broad setups where
#: over-matching costs a slightly-off plan; here a false match on `model_answer` means
#: showing a candidate the ideal answer to a DIFFERENT question, which is worse than
#: paying for the generation. When in doubt, miss and pay.
_SIMILARITY_THRESHOLD = 0.93

#: Cosine DISTANCE ceiling, which is what pgvector's `<=>` returns.
_MAX_DISTANCE = 1.0 - _SIMILARITY_THRESHOLD

#: Rows kept per feature before LRU eviction. Generous: the whole point of an index is
#: that hundreds of entries cost nothing to search, and the question bank is finite.
_MAX_ROWS_PER_FEATURE = 5_000

#: Run eviction on every Nth write rather than every write. The DELETE is much more
#: expensive than the INSERT it follows, and the only cost of batching is that a feature
#: can sit up to this many rows above its cap.
_EVICT_EVERY = 50
_writes_since_evict = 0


def normalize_key(key: str) -> str:
    """
    Canonical form of a cache key: lowercased, tokenised, domain synonyms folded,
    setup AND question stopwords dropped, then sorted.

    Sorted because word order carries no meaning for these keys — "Java, Spring" and
    "Spring, Java" are one request — and sorting is what makes the exact-hash fast path
    catch them without needing the vector search at all.
    """
    return " ".join(sorted(_key_tokens(key)))


def key_hash(key: str) -> str:
    """SHA-256 of the normalised key. Exact-match fast path and uniqueness guarantee."""
    return hashlib.sha256(normalize_key(key).encode("utf-8")).hexdigest()


def embed(key: str) -> list[float]:
    """
    Turn a cache key into a fixed-width unit vector.

    THIS IS THE ONLY FUNCTION THAT KNOWS HOW A VECTOR IS BUILT. Replacing it with a
    call to a real embedding model is the entire upgrade — the table, the HNSW index,
    the lookup, the store and every call site are unchanged, save for matching
    EMBEDDING_DIM to the new model.

    The method is the hashing trick: each canonical token is hashed to one of
    EMBEDDING_DIM buckets and contributes its weight there. Sub-token character
    trigrams are added at a lower weight so a near-miss spelling that survives
    canonicalisation ("Hashtable" vs "Hash table" once tokenised differently) still
    lands close, rather than being orthogonal the way pure token hashing would make it.

    L2-normalised, so the cosine distance the index computes is meaningful and every
    vector is comparable.
    """
    vec = [0.0] * EMBEDDING_DIM
    tokens = _key_tokens(key)
    if not tokens:
        return vec

    def bucket(s: str) -> int:
        # blake2b rather than Python's hash(): hash() is randomised per process by
        # PYTHONHASHSEED, so vectors written by one container would be meaningless to
        # the next. That would silently reduce the cache's hit rate to zero after every
        # deploy, with no error anywhere.
        return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=4).digest(), "big") % EMBEDDING_DIM

    for tok in tokens:
        vec[bucket(tok)] += 1.0
        # Character trigrams at a fifth of the weight: enough to pull near-spellings
        # together, not enough to let two unrelated keys that share common letter runs
        # cross the threshold.
        padded = f"^{tok}$"
        for i in range(len(padded) - 2):
            vec[bucket(padded[i : i + 3])] += 0.2

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def _as_pgvector(vec: list[float]) -> str:
    """pgvector's text input form: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


class UncacheableFeature(ValueError):
    """Raised when a feature not on the allowlist is offered to the cache."""


def _require_cacheable(feature: str) -> None:
    if feature not in CACHEABLE_FEATURES:
        raise UncacheableFeature(
            f"'{feature}' is not in CACHEABLE_FEATURES. If its input includes anything "
            "a candidate said, it must NOT be cached across users — see the tenancy "
            "note in this module. If it is genuinely public topic data, add it to the "
            "allowlist deliberately."
        )


async def lookup(
    db: AsyncSession,
    *,
    feature: str,
    key: str,
    scope: str = GLOBAL_SCOPE,
) -> dict | None:
    """
    Find a cached generation for this key, or None.

    Two stages: an exact hash match, then a nearest-neighbour search. The exact match
    exists because it is the common case — the same question asked again — and it costs
    one index probe instead of an ANN search.

    A hit bumps `hit_count` and `last_used_at` in the same statement that reads the
    payload, which is the "updated whenever anyone uses it" half of the design: the
    cache warms from real traffic with no seed job, and LRU eviction has something
    honest to sort on.

    Never raises. A cache that can fail a request is worse than no cache, so every
    error degrades to a miss and the caller pays for the generation as before.
    """
    _require_cacheable(feature)
    try:
        # Exact match. UPDATE ... RETURNING so the hit is counted and the payload read
        # in one round trip, with no read-then-write race.
        row = (
            await db.execute(
                text(
                    """
                    UPDATE ai_cache
                       SET hit_count = hit_count + 1, last_used_at = now()
                     WHERE feature = :feature AND scope = :scope AND key_hash = :kh
                    RETURNING payload
                    """
                ),
                {"feature": feature, "scope": scope, "kh": key_hash(key)},
            )
        ).first()
        if row is not None:
            logger.debug("ai_cache_hit_exact", feature=feature, key=key[:80])
            return dict(row[0])

        # Near match. The subquery does the ANN search; the UPDATE counts the hit.
        vec = embed(key)
        if not any(vec):
            return None
        row = (
            await db.execute(
                text(
                    """
                    UPDATE ai_cache
                       SET hit_count = hit_count + 1, last_used_at = now()
                     WHERE id = (
                             SELECT id FROM ai_cache
                              WHERE feature = :feature
                                AND scope = :scope
                                AND embedding IS NOT NULL
                                AND embedding <=> CAST(:vec AS vector) <= :maxd
                              ORDER BY embedding <=> CAST(:vec AS vector)
                              LIMIT 1
                           )
                    RETURNING payload, cache_key
                    """
                ),
                {
                    "feature": feature,
                    "scope": scope,
                    "vec": _as_pgvector(vec),
                    "maxd": _MAX_DISTANCE,
                },
            )
        ).first()
        if row is not None:
            logger.info(
                "ai_cache_hit_similar",
                feature=feature,
                wanted=key[:80],
                served=str(row[1])[:80],
            )
            return dict(row[0])
        return None

    except Exception:
        # Degrade to a miss. Notably this also covers "migration 014 has not been run
        # yet", so deploying the code before the migration costs money rather than
        # breaking every feature that consults the cache.
        logger.warning("ai_cache_lookup_failed", feature=feature, exc_info=True)
        return None


async def store(
    db: AsyncSession,
    *,
    feature: str,
    key: str,
    payload: dict,
    scope: str = GLOBAL_SCOPE,
) -> None:
    """
    Remember a generation.

    ON CONFLICT DO UPDATE rather than DO NOTHING: two requests for the same key
    arriving together both generate (the cache cannot prevent that — only a lock could,
    and a lock in front of a cache is a worse trade), and the newer payload is as good
    as the older one. Doing nothing would be equally correct; updating keeps the row's
    freshness honest.

    Never raises, for the same reason as `lookup`: failing to remember an answer must
    not fail the request that produced it.
    """
    _require_cacheable(feature)
    try:
        await db.execute(
            text(
                """
                INSERT INTO ai_cache
                       (feature, cache_key, key_hash, scope, payload, embedding,
                        hit_count, last_used_at)
                VALUES (:feature, :ck, :kh, :scope, CAST(:payload AS jsonb),
                        CAST(:vec AS vector), 0, now())
                ON CONFLICT (feature, key_hash) DO UPDATE
                    SET payload = EXCLUDED.payload, last_used_at = now()
                """
            ),
            {
                "feature": feature,
                # Bounded to the column width. The full key is not needed to serve a
                # hit — the hash and the vector do that — it is for debugging.
                "ck": (key or "")[:500],
                "kh": key_hash(key),
                "scope": scope,
                "payload": json.dumps(payload),
                "vec": _as_pgvector(embed(key)),
            },
        )
        logger.debug("ai_cache_stored", feature=feature, key=key[:80])

        # Trim opportunistically. Railway runs one service and there is no scheduler, so
        # if eviction is not driven from the write path it never happens at all — which is
        # how a cache becomes a slow disk-space outage. (It was documented as
        # "called opportunistically after a store" and then never called: caught by
        # noticing evict_lru had no callers.)
        #
        # Every _EVICT_EVERY writes rather than every write, because a DELETE with an
        # OFFSET subquery is far more expensive than the INSERT it follows and the table
        # cannot overshoot its cap by more than that many rows.
        global _writes_since_evict
        _writes_since_evict += 1
        if _writes_since_evict >= _EVICT_EVERY:
            _writes_since_evict = 0
            removed = await evict_lru(db, feature=feature)
            if removed:
                logger.info("ai_cache_evicted", feature=feature, removed=removed)
    except Exception:
        logger.warning("ai_cache_store_failed", feature=feature, exc_info=True)


async def evict_lru(db: AsyncSession, *, feature: str) -> int:
    """
    Trim a feature back to _MAX_ROWS_PER_FEATURE, dropping least-recently-used first.

    Called opportunistically after a store rather than on a schedule, because Railway
    runs one service and there is no scheduler — and a cache that grows without bound
    is a slow disk-space outage rather than a fast one.
    """
    try:
        # CursorResult exposes rowcount; the AsyncSession's declared Result type does
        # not, so this is narrowed rather than ignored.
        result: CursorResult = await db.execute(  # type: ignore[assignment]
            text(
                """
                DELETE FROM ai_cache
                 WHERE id IN (
                         SELECT id FROM ai_cache
                          WHERE feature = :feature
                          ORDER BY last_used_at DESC
                         OFFSET :keep
                       )
                """
            ),
            {"feature": feature, "keep": _MAX_ROWS_PER_FEATURE},
        )
        return result.rowcount or 0
    except Exception:
        logger.warning("ai_cache_evict_failed", feature=feature, exc_info=True)
        return 0


async def stats(db: AsyncSession) -> list[dict]:
    """
    Per-feature cache performance, for the admin usage screen.

    `hit_count` totals are the only honest answer to "is this cache earning its keep".
    A feature whose entries are mostly hit_count=0 is one where caching bought nothing
    and should be reconsidered rather than left to accumulate rows.
    """
    try:
        rows = await db.execute(
            text(
                """
                SELECT feature,
                       count(*)                    AS entries,
                       coalesce(sum(hit_count), 0) AS hits,
                       count(*) FILTER (WHERE hit_count = 0) AS never_hit,
                       max(last_used_at)           AS last_used
                  FROM ai_cache
                 GROUP BY feature
                 ORDER BY hits DESC
                """
            )
        )
        return [
            {
                "feature": r.feature,
                "entries": int(r.entries),
                "hits": int(r.hits),
                "never_hit": int(r.never_hit),
                # Generations avoided x roughly what that feature costs is the saving;
                # the caller joins this against the cost ledger to price it.
                "last_used": r.last_used.isoformat() if r.last_used else None,
            }
            for r in rows
        ]
    except Exception:
        logger.warning("ai_cache_stats_failed", exc_info=True)
        return []
