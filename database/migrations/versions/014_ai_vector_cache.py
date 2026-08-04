"""pgvector-backed cache for reusable AI generations

WHY THIS EXISTS.

The cheapest AI call is the one you never make. Measured against list price, one full
12-question interview costs about 23 cents and one 8-minute GD round about 36 cents,
so the AI bill — not hosting — is what decides whether this product can carry a
thousand users. Some of those generations are genuinely per-candidate and can never
be reused. Several are not: the ideal answer to "What is the difference between
HashMap and Hashtable?" is the same for every candidate who is asked it, and this
question bank is finite.

WHERE THE EMBEDDINGS COME FROM, AND WHY.

Anthropic sells no embeddings endpoint, so the honest options were a paid embeddings
API (Voyage, OpenAI, Cohere), a local sentence-transformer in the container, plain
Postgres full-text similarity, or hashing lexical features into a fixed-width vector.
This uses the last one:

  * No new API key, no new bill, and — the deciding factor — no new network call in
    the request path. An embeddings provider being slow or down would make a CACHE
    LOOKUP a source of latency and failure, which is the opposite of the point.
  * A local transformer model adds hundreds of megabytes and cold-start seconds to a
    Railway container that currently starts in seconds.
  * The keys being matched are 2-8 words of domain jargon — "HashMap vs Hashtable",
    "Cognizant GenC Next", "AI in education". Dense semantic embeddings earn their
    cost on paragraphs, not on phrases from a closed vocabulary; hashed lexical
    features plus a synonym map handle this shape essentially as well, for free.

The upgrade path is deliberately open and cheap: `embed()` in
services/ai/vector_cache.py is the ONLY function that knows how a vector is built.
Swapping in real embeddings later is a change to that one function plus a dimension
change here — the table, the index, the protocol and every call site stay as they are.

WHY POSTGRES RATHER THAN THE EXISTING REDIS CACHE.

There is already a Redis semantic cache for interview plans
(services/ai/semantic_cache.py). It works, and this does not replace it — it does the
two things Redis could not:

  * DURABILITY. The Redis cache is a cache in the strict sense: a restart or eviction
    loses every entry and the next candidate pays full price again. Cached AI output
    is expensive enough to be worth keeping on disk.
  * AN INDEX. The Redis version linearly scans a capped list of 200 signatures, which
    is why it is capped. An HNSW index over pgvector searches tens of thousands of
    entries in single-digit milliseconds, which is what makes caching per-QUESTION
    (hundreds of entries) rather than per-company (dozens) practical at all.

WHAT MAY AND MAY NOT BE CACHED HERE — THE TENANCY RULE.

This is the load-bearing design constraint, and it is not a performance question.
This app has already shipped a bug where one candidate was asked to explain a phrase
another candidate had said, and migration 010 (questions.session_id) exists because of
it. So the rule is absolute: ONLY generations whose input is public, topic-level data
may be cached here. Concretely —

  CACHEABLE   model_answer (keyed on the question), quiz_generation (topic +
              difficulty), gd_topic_prep (a topic phrase), interview_plan (company +
              program + focus). None of these read a candidate's answers.

  NEVER       cross_question, report_generation, gd_evaluation, communication_*,
              code_analysis. Every one of them is generated FROM a specific
              candidate's answer. Caching any of them across users would be the same
              class of defect as the bug migration 010 fixed, and no saving justifies
              it. The `scope` column exists so this is enforced in data and not only
              in review: a row is either 'global' or carries the user it belongs to.

"UPDATED WHENEVER ANYONE USES IT" — the write path.

A miss inserts the generation. A hit bumps `hit_count` and `last_used_at`, which is
what makes the cache warm itself as traffic arrives rather than needing a seed job,
and what gives LRU eviction something honest to sort on. `hit_count` is also the only
way to answer "is this cache actually earning its keep" — a table full of entries with
hit_count 1 is a table of wasted writes.

DESIGN NOTES THAT MATTER IF YOU TOUCH THIS.

  * vector(512) with an HNSW index using `vector_cosine_ops`, matching the cosine
    distance operator (<=>) the lookup uses. An index built for a different operator
    class is silently not used, and the only symptom is a slow query.
  * pgvector lives in the `extensions` schema on Supabase, not `public`. CREATE
    EXTENSION IF NOT EXISTS is still issued so a local Postgres and a fresh Supabase
    project both work; on Supabase it is already enabled and this is a no-op.
  * UNIQUE (feature, key_hash) so the same exact key cannot be stored twice. The
    vector search finds NEAR matches; this stops the degenerate case where the same
    string is inserted repeatedly by concurrent requests.
  * RLS enabled with no policy, matching migrations 012 and 013. The app connects as
    table owner and bypasses RLS; this closes the table to the public anon key, which
    reaches Postgres through PostgREST where RLS is NOT bypassed. Without it this
    table would be world-readable — and it holds generated interview content.
  * NO foreign key to users on `scope`. A cache entry outliving its creator is fine;
    a cascade delete quietly emptying the cache when a user is removed is not.

Revision ID: 014
Revises: 013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

#: Dimensions of the hashed lexical vector. 512 is far more than the vocabulary of
#: this domain needs — collisions are already rare at 256 — and keeps the HNSW index
#: small. If `embed()` is ever swapped for a real embedding model this must change to
#: match it (1536 for OpenAI text-embedding-3-small, 1024 for Voyage), which is a
#: rebuild of the column and the index, not a migration of the data: cached rows
#: whose vectors were produced by a different function are meaningless and should be
#: truncated rather than converted.
_DIM = 512


def upgrade() -> None:
    # Already enabled on Supabase (extensions schema); this makes a local Postgres or
    # a fresh project work without a manual step.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "ai_cache",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        #: The `context=` label from the generate_structured call site — the same
        #: string the cost ledger uses, so cache performance and cost per feature can
        #: be joined without a mapping table.
        sa.Column("feature", sa.String(64), nullable=False),
        #: The human-readable key this entry was generated for, kept for debugging a
        #: surprising hit. Bounded because it is user-influenced text.
        sa.Column("cache_key", sa.String(500), nullable=False),
        #: SHA-256 of the normalised key. Exact-match fast path and the uniqueness
        #: guarantee; the vector handles near matches.
        sa.Column("key_hash", sa.String(64), nullable=False),
        #: 'global' for generations derived only from public topic data. Anything
        #: derived from a candidate's own answers must carry their user id here and
        #: must only ever be served back to them. See the tenancy note above.
        sa.Column("scope", sa.String(64), nullable=False, server_default=sa.text("'global'")),
        #: The generation itself, as the JSON the caller's Pydantic schema parses.
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("feature", "key_hash", name="uq_ai_cache_feature_key"),
    )

    # The vector column, added separately because Alembic has no native vector type.
    op.execute(f"ALTER TABLE ai_cache ADD COLUMN embedding vector({_DIM})")

    # HNSW with vector_cosine_ops, matching the `<=>` operator the lookup uses. An
    # index built for a different operator class is simply never used, and the only
    # symptom is that queries stay slow.
    op.execute(
        "CREATE INDEX ix_ai_cache_embedding ON ai_cache "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # Every lookup filters by feature and scope before the vector search, so this
    # composite is what keeps the ANN search over a small candidate set.
    op.create_index("ix_ai_cache_feature_scope", "ai_cache", ["feature", "scope"])
    # LRU eviction orders by this.
    op.create_index("ix_ai_cache_last_used", "ai_cache", ["last_used_at"])

    op.execute("ALTER TABLE public.ai_cache ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_ai_cache_last_used", table_name="ai_cache")
    op.drop_index("ix_ai_cache_feature_scope", table_name="ai_cache")
    op.execute("DROP INDEX IF EXISTS ix_ai_cache_embedding")
    op.drop_table("ai_cache")
    # The extension is deliberately NOT dropped: it may be in use by something else,
    # and on Supabase it is managed through the dashboard.
