"""scope AI-generated questions to the session that produced them

THE BUG THIS FIXES. A candidate was shown, as a fresh question:

    "You mentioned 'annual function' in your answer instead of method overriding
     or overloading — can you tell me what those two terms mean in Java?"

They had never answered a question on overriding or overloading, and had never
said "annual function". Somebody else had.

Every AI-generated question was written into the shared `questions` table with
nothing but a `topic_id`, and every pool query read the whole track:

    orchestrator._track_questions()   select(Question) join Topic join Category
                                      where category.track_id = :track
    get_next_question fallback        select(Question) with NO filter at all

Four call sites write into that pool, and three of them produce text that is
specific to one person:

  _generate_cross_question  quotes the candidate's own words back at them. This
                            is the one that leaked — a live cross-question built
                            from one candidate's garbled speech-to-text was
                            persisted under the track's topic, and the next
                            candidate's plan picked it up as a normal question.
  _persist_plan             resume-tailored questions. "You mentioned building a
                            payments service at <employer>" is somebody's CV.
  _generate_question        adaptive questions aimed at the gaps a specific
                            candidate just revealed.
  _ensure_seed_questions    static YAML seed content. Genuinely shared.

So this was both a correctness bug and a tenancy leak: one user's spoken answer
and resume details could surface verbatim inside another user's interview.

THE FIX. `questions.session_id`:

    NULL      a question bank row. Seeded, generic, reusable by anyone.
    non-NULL  generated for exactly one session. Never served to another.

Every pool query now filters `session_id IS NULL`. A session still reaches its
own generated questions, because those are fetched by explicit id out of
`session_metadata.planned_question_ids` / `cross_question_ids`, never by search.

This is a column rather than a `is_generated` boolean on purpose. A boolean would
keep generated questions out of the pool but would not say WHOSE they are, so
`submit_answer` still could not check that an answer is being filed against a
question this session was actually asked. With the owner recorded, that check is
one comparison.

THE BACKFILL. Existing rows are not guesswork — every session already records the
questions it generated, in `session_metadata`. `planned_question_ids` and
`cross_question_ids` are exact, so the backfill reads them straight out of the
JSONB and assigns ownership from the data itself. Anything not claimed by a
session stays NULL and remains a bank question, which is the safe default: the
worst case is that a generic question stays reusable.

ON DELETE CASCADE, because a generated question has no meaning once its session
is gone, and answers already cascade from the session.

Revision ID: 010
Revises: 009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("session_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_questions_session_id",
        "questions",
        "interview_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Partial index. Every pool query is `WHERE session_id IS NULL`, and the bank
    # is the small minority of rows once generated questions accumulate, so
    # indexing only the NULLs keeps the index tiny and exactly matches the
    # predicate. A full index on a mostly-non-NULL column would be larger and
    # would not serve this query any better.
    op.create_index(
        "ix_questions_bank",
        "questions",
        ["session_id"],
        unique=False,
        postgresql_where=sa.text("session_id IS NULL"),
    )

    # Backfill from what the sessions already recorded. Both keys are JSONB
    # arrays of UUID strings; jsonb_array_elements_text unnests them and the cast
    # matches the questions PK. `jsonb_typeof = 'array'` guards the rows written
    # before either key existed, where the value is absent or null.
    for key in ("planned_question_ids", "cross_question_ids"):
        op.execute(
            sa.text(
                f"""
                UPDATE questions q
                   SET session_id = s.id
                  FROM interview_sessions s
                 CROSS JOIN LATERAL jsonb_array_elements_text(
                          s.session_metadata -> '{key}'
                       ) AS owned(qid)
                 WHERE jsonb_typeof(s.session_metadata -> '{key}') = 'array'
                   AND q.id = owned.qid::uuid
                   AND q.session_id IS NULL
                """
            )
        )


def downgrade() -> None:
    op.drop_index("ix_questions_bank", table_name="questions")
    op.drop_constraint("fk_questions_session_id", "questions", type_="foreignkey")
    op.drop_column("questions", "session_id")
