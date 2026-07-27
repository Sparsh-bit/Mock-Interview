"""
Semantic cache for reusable AI work — semantic_cache.py

The cheapest AI call is the one you never make. Interview plans are the most
expensive generation in the app, and candidates overwhelmingly cluster on a
handful of setups (Cognizant GenC / GenC Next / Java FSE, TCS, Infosys), so
most requests are a near-duplicate of one we've already paid for.

The pre-existing cache keyed a SHA-1 of `company|program|focus`, which only
reuses on a byte-identical signature. These all missed and each cost a fresh
generation:

    "Java, Spring"      vs "Spring, Java"        (token order)
    "Cognizant GenC"    vs "Cognizant Gen C"     (spacing)
    "Java FSE"          vs "Java Full Stack Eng" (abbreviation)

This module matches on *meaning* instead: each signature becomes a sparse
vector over normalized tokens, and lookup is a cosine-similarity search over
previously cached signatures.

── Why sparse lexical vectors and not neural embeddings ─────────────────────
Anthropic does not sell an embeddings endpoint, so dense embeddings would mean
adding a second provider (Voyage, OpenAI) — another API key, another bill,
another failure path — to compare strings that are 2-6 words of domain jargon.
Sparse token vectors plus a domain synonym map handle that shape of input
essentially as well, for free and with no network call.

The design keeps the upgrade open: `_vectorize` and `_similarity` are the only
two places that know how vectors are made and compared. To move to pgvector +
real embeddings, reimplement those two functions — the cache protocol, Redis
layout, and every call site stay as they are.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

import structlog

from app.db.redis import cache_get, cache_set, get_redis

logger = structlog.get_logger(__name__)

# ─── Tuning ───────────────────────────────────────────────────────────────────

#: Cosine similarity at or above which two signatures are "the same setup".
#: 0.82 was chosen to accept word-order and abbreviation differences while
#: still separating genuinely different programs — "Cognizant GenC" must not
#: match "Cognizant GenC Next", which is a harder interview with its own plan.
_SIMILARITY_THRESHOLD = 0.82

#: Cap on indexed signatures. Bounds both the Redis value size and the linear
#: scan; well above the number of distinct company/program combos in practice.
_MAX_INDEXED_SIGNATURES = 200

_INDEX_KEY = "plan:sigindex"
_INDEX_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

# Tokens that carry no distinguishing signal for an interview setup.
_STOPWORDS = frozenset({
    "a", "an", "and", "the", "for", "of", "to", "in", "on", "with", "or",
    "no", "not", "any", "some", "specific", "general", "standard", "role",
    "fresher", "freshers", "candidate", "interview", "round", "job",
})

# Domain synonyms, mapped to a canonical token. This is where most of the real
# matching power lives — placement jargon has many spellings for one thing.
_SYNONYMS: dict[str, str] = {
    # Cognizant Digital Nurture programs
    "genc": "genc",
    "gen": "genc",          # "gen c" → genc (paired with the 'c' drop below)
    "gencnext": "gencnext",
    "next": "gencnext",     # only meaningful following genc; see _canonicalize
    "dn": "digitalnurture",
    "digitalnurture": "digitalnurture",
    "nurture": "digitalnurture",
    # Roles
    "fse": "fullstack",
    "fullstack": "fullstack",
    "full": "fullstack",
    "stack": "fullstack",
    "sde": "softwareengineer",
    "swe": "softwareengineer",
    "engineer": "softwareengineer",
    "developer": "softwareengineer",
    "dev": "softwareengineer",
    # Tech
    "springboot": "spring",
    "spring": "spring",
    "js": "javascript",
    "javascript": "javascript",
    "reactjs": "react",
    "react": "react",
    "nodejs": "node",
    "node": "node",
    "postgres": "sql",
    "postgresql": "sql",
    "mysql": "sql",
    "oracle": "sql",
    "dbms": "sql",
    "database": "sql",
    "databases": "sql",
    "oop": "oops",
    "oops": "oops",
    "ds": "datastructures",
    "dsa": "datastructures",
    "datastructures": "datastructures",
    "algorithms": "datastructures",
    "algo": "datastructures",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


# ─── Vectorization ────────────────────────────────────────────────────────────


def _canonicalize(tokens: list[str]) -> list[str]:
    """Fold spelling variants onto canonical tokens."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]

        # "gen c" / "gen c next" → genc / gencnext
        if tok == "gen" and i + 1 < len(tokens) and tokens[i + 1] == "c":
            if i + 2 < len(tokens) and tokens[i + 2] == "next":
                out.append("gencnext")
                i += 3
                continue
            out.append("genc")
            i += 2
            continue

        # "genc next" → gencnext (one program, not two tokens)
        if tok == "genc" and i + 1 < len(tokens) and tokens[i + 1] == "next":
            out.append("gencnext")
            i += 2
            continue

        if tok in _STOPWORDS:
            i += 1
            continue

        out.append(_SYNONYMS.get(tok, tok))
        i += 1
    return out


def _vectorize(company: str, program: str, focus: str) -> dict[str, float]:
    """
    Turn a plan signature into a sparse weighted vector over canonical tokens.

    Company and program identify *which* interview this is and are weighted
    heavily; focus areas are a softer preference, so a differing focus alone
    should not force a regeneration.

    Swap this (with `_similarity`) for a real embedding call to move to a dense
    vector store — nothing else in the module depends on the representation.
    """
    vec: dict[str, float] = {}
    for text, weight in ((company, 3.0), (program, 3.0), (focus, 1.0)):
        tokens = _canonicalize(_TOKEN_RE.findall((text or "").lower()))
        for tok in tokens:
            vec[tok] = vec.get(tok, 0.0) + weight
    return vec


def _similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity of two sparse vectors. 0.0 when either is empty."""
    if not a or not b:
        return 0.0
    dot = sum(w * b.get(tok, 0.0) for tok, w in a.items())
    if not dot:
        return 0.0
    norm_a = math.sqrt(sum(w * w for w in a.values()))
    norm_b = math.sqrt(sum(w * w for w in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def variant_key(company: str, program: str, focus: str) -> str:
    """
    Stable Redis key for a signature's variant bucket.

    Derived from the *canonical* token set, so signatures that differ only in
    word order, spacing, or abbreviation share one bucket without needing a
    similarity search at all.
    """
    vec = _vectorize(company, program, focus)
    sig = "|".join(sorted(vec))
    digest = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]  # noqa: S324 — cache key, not security
    return f"plan:variants:{digest}"


# ─── Redis-backed index ───────────────────────────────────────────────────────


async def _load_index() -> list[dict]:
    """Load the signature index. Best-effort — never raises."""
    try:
        raw = await cache_get(get_redis(), _INDEX_KEY)
        if raw:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
    except Exception as exc:  # noqa: BLE001 — cache is best-effort
        logger.warning("semantic_index_load_failed", error=str(exc))
    return []


async def _save_index(index: list[dict]) -> None:
    """Persist the signature index. Best-effort — never raises."""
    try:
        await cache_set(
            get_redis(),
            _INDEX_KEY,
            json.dumps(index[-_MAX_INDEXED_SIGNATURES:]),
            ttl=_INDEX_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — cache is best-effort
        logger.warning("semantic_index_save_failed", error=str(exc))


async def find_similar_key(company: str, program: str, focus: str) -> str | None:
    """
    Find the variant key of a previously cached, semantically-equivalent setup.

    Returns None when nothing clears the similarity threshold, in which case
    the caller should generate and then call `register`.

    Never raises: a cache miss must degrade to a normal generation, never break
    an interview.
    """
    query = _vectorize(company, program, focus)
    if not query:
        return None

    exact = variant_key(company, program, focus)
    best_key: str | None = None
    best_score = 0.0

    for entry in await _load_index():
        key = entry.get("key")
        vec = entry.get("vec")
        if not key or not isinstance(vec, dict):
            continue
        if key == exact:
            # Canonical-key hit — nothing can score higher than itself.
            return key
        score = _similarity(query, vec)
        if score > best_score:
            best_key, best_score = key, score

    if best_key and best_score >= _SIMILARITY_THRESHOLD:
        logger.info(
            "semantic_cache_hit",
            similarity=round(best_score, 3),
            threshold=_SIMILARITY_THRESHOLD,
            key=best_key,
        )
        return best_key

    logger.debug(
        "semantic_cache_miss",
        best_similarity=round(best_score, 3),
        threshold=_SIMILARITY_THRESHOLD,
    )
    return None


async def register(company: str, program: str, focus: str) -> str:
    """
    Record a signature in the index so future similar setups reuse its plan.
    Returns the variant key the caller should store plan variants under.
    """
    key = variant_key(company, program, focus)
    vec = _vectorize(company, program, focus)

    index = await _load_index()
    # Replace any existing entry for this key so the vector stays current and
    # the index doesn't grow duplicates.
    index = [e for e in index if e.get("key") != key]
    index.append({"key": key, "vec": vec})
    await _save_index(index)
    return key
