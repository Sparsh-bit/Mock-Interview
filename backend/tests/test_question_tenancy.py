"""
Guards on the question-pool tenancy boundary.

WHY THIS FILE EXISTS. A candidate was served this as a fresh interview question:

    "You mentioned 'annual function' in your answer instead of method overriding
     or overloading — can you tell me what those two terms mean in Java?"

They had never answered a question on overriding, and had never said "annual
function". Another candidate had, into a microphone, and the speech-to-text
mangled it. The live cross-question built from that mangled answer was written
into the shared `questions` table under the track's topic, and the next
candidate's plan selected it out of the pool like any other question.

The API layer was not at fault — every session endpoint verifies ownership. The
leak was one level below it, in a table nobody thought of as per-user: three of
the four places that create questions produce text about one specific person,
and every pool query read the whole track.

The tests here are deliberately structural rather than behavioural. A test that
runs one interview and asserts it saw no foreign questions passes for the wrong
reason on an empty database, which is precisely the state a fresh test run is
in. Reading the source for a missing filter fails the moment someone adds the
fifth pool query and forgets, which is how this class of bug actually recurs.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.models.question import Question
from app.services.interview import orchestrator as orch

ORCHESTRATOR_SRC = Path(inspect.getfile(orch)).read_text()
TREE = ast.parse(ORCHESTRATOR_SRC)


def _select_question_statements() -> list[tuple[int, str]]:
    """
    Every statement in the orchestrator containing a `select(Question...)` call,
    as (line number, source of the whole statement).

    Whole statements, not lines: these queries are chained across several lines,
    so a per-line check would report a false failure on the `select(Question)`
    line of a perfectly correct multi-line query.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.stmt):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "select"
                and sub.args
                and isinstance(sub.args[0], ast.Name)
                and sub.args[0].id == "Question"
            ):
                found.append((node.lineno, ast.get_source_segment(ORCHESTRATOR_SRC, node) or ""))
                break
    return found


class TestQuestionModel:
    def test_question_has_a_session_owner_column(self):
        """
        NULL means a shared bank row; non-NULL means it belongs to one session.
        Without this column there is nothing to filter on and the pool queries
        cannot be written correctly at all.
        """
        assert "session_id" in Question.__table__.columns, (
            "questions.session_id is the tenancy boundary for generated questions."
        )

    def test_session_owner_is_nullable(self):
        """
        NOT NULL would be wrong: seeded bank questions genuinely have no owner,
        and forcing one would either invent a fake session or push every seed
        into somebody's interview.
        """
        assert Question.__table__.columns["session_id"].nullable is True

    def test_session_owner_cascades(self):
        """A generated question has no meaning once its session is deleted."""
        fks = list(Question.__table__.columns["session_id"].foreign_keys)
        assert len(fks) == 1, "session_id must be a real FK, not a loose UUID"
        assert fks[0].column.table.name == "interview_sessions"
        assert fks[0].ondelete == "CASCADE"


class TestPoolQueriesAreScoped:
    """
    The load-bearing test. Any query that SEARCHES for questions must restrict
    itself to the bank; only lookups by explicit primary key may return a
    session-owned question, because those ids come from the session's own
    metadata and are therefore already scoped.
    """

    def test_every_select_question_filters_on_session(self):
        unscoped = [
            (lineno, src.strip().splitlines()[0][:88])
            for lineno, src in _select_question_statements()
            if "session_id" not in src
        ]
        assert not unscoped, (
            "select(Question) without a session_id filter — this is exactly the bug "
            "that served one candidate's answer to another:\n"
            + "\n".join(f"  orchestrator.py:{n}  {s}" for n, s in unscoped)
        )

    def test_there_is_at_least_one_pool_query_to_guard(self):
        """
        Stops the test above from passing vacuously if the queries are renamed or
        moved and the scan silently finds nothing.
        """
        assert len(_select_question_statements()) >= 3


class TestGeneratedQuestionsAreOwned:
    """
    The other half: a query filter is useless if the rows are never marked.
    Every Question(...) constructed in the orchestrator must either set
    session_id, or be the seed path that deliberately does not.
    """

    def test_every_constructed_question_sets_an_owner_or_is_a_seed(self):
        unowned: list[int] = []
        for node in ast.walk(TREE):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Question"
            ):
                continue
            kwargs = {kw.arg for kw in node.keywords}
            if "session_id" not in kwargs:
                unowned.append(node.lineno)

        # _ensure_seed_questions builds the shared bank and is the one legitimate
        # exception. Pin it by count rather than by line number, which drifts.
        assert len(unowned) <= 1, (
            "Question(...) built without session_id at orchestrator.py lines "
            f"{unowned}. Only the seed-bank path may omit it; everything else "
            "must record which session it belongs to."
        )


class TestCrossQuestionGuard:
    """
    The cross-question prompt's entire job is to dig into what the candidate
    said. Handed a two-word fragment it has nothing to dig into, and it fills
    the gap by attributing the expected answer to them.
    """

    def test_minimum_is_a_clause_not_a_word(self):
        assert 8 <= orch._MIN_WORDS_FOR_CROSS_QUESTION <= 25, (
            "Too low and a mis-fired mic still triggers a follow-up; too high and "
            "genuine short answers never get probed."
        )

    @pytest.mark.parametrize(
        "answer",
        [
            "",
            "annual function",
            "I don't know",
            "next question please",
            "yes",
        ],
    )
    def test_non_answers_are_below_the_threshold(self, answer: str):
        assert len(answer.split()) < orch._MIN_WORDS_FOR_CROSS_QUESTION

    def test_a_real_if_weak_answer_is_above_the_threshold(self):
        answer = (
            "I think the JVM is like a virtual machine that runs java code and it "
            "handles memory"
        )
        assert len(answer.split()) >= orch._MIN_WORDS_FOR_CROSS_QUESTION


class TestPersonalFocusIsNotCached:
    """
    "Anything specific?" is free text, it goes into the plan prompt, and the
    resulting plan is cached under a signature derived from that same text. So a
    focus written in the first person has to be treated like a resume.
    """

    @pytest.mark.parametrize(
        "focus",
        [
            "I struggle with multithreading",
            "my internship at a payments company",
            "we built a React dashboard",
            "Can you go easy on me",
            "I'd like more DSA",
        ],
    )
    def test_first_person_focus_is_personal(self, focus: str):
        assert orch._is_personal_focus(focus) is True

    @pytest.mark.parametrize(
        "focus",
        [
            "",
            "Spring Boot, SQL, DBMS",
            "Focus on OOPs and collections",
            "system design and algorithms",
        ],
    )
    def test_topic_lists_are_not_personal(self, focus: str):
        assert orch._is_personal_focus(focus) is False

    def test_substrings_do_not_false_positive(self):
        """
        Word-boundary matching, not substring. "Docker Images" contains "i" and
        "me" as substrings; treating those as first person would make almost
        every focus uncacheable and quietly delete the cache's whole benefit.
        """
        assert orch._is_personal_focus("Docker Images and Microservices") is False
        assert orch._is_personal_focus("Time complexity, memory management") is False


class TestTheTypedFocusNeverEntersTheSharedPool:
    """
    `$candidate_focus` reaches the per-session generator and never the shared batch.

    WHY THIS NEEDS ITS OWN TEST. The candidate reported that the setup screen's "Anything
    specific?" box did nothing, and the fix was to feed it to every path that produces a
    question. `_bank_question` is a path that produces questions — and it is the one path
    that must not have it, because its output is cached in `question_bank` and served to
    OTHER candidates on the same track. CLAUDE.md's tenancy rule is that nothing derived
    from one candidate may reach another, and the setup box is candidate input.

    So the obvious version of the fix is wrong in a way that no failing test would have
    shown: it would work, the box would be honoured, and one candidate's preference would
    quietly shape the questions everybody on that track is asked next — and be billed to
    them. `tests/test_prompt_wiring.py` checks that both call sites pass SOMETHING for the
    variable. This checks they pass the right something.
    """

    def test_the_shared_pool_site_passes_a_sentinel_and_not_a_value(self):
        src = inspect.getsource(orch.InterviewOrchestrator._bank_question)
        assert "candidate_focus=" in src, (
            "the shared-pool call site must pass candidate_focus explicitly — omitting it "
            "sends the literal '$candidate_focus' to the model, because substitution is "
            "safe_substitute"
        )
        assert "shared pool" in src
        # The one thing that must not appear: the session, or anything read off it.
        assert "session_metadata" not in src
        assert "_candidate_focus_block" not in src

    def test_the_per_session_site_passes_the_real_thing(self):
        src = inspect.getsource(orch.InterviewOrchestrator._generate_question)
        assert "candidate_focus=_candidate_focus_block(session)" in src

    def test_the_block_reads_the_pinned_value_rather_than_re_deriving_it(self):
        # create_plan wrote it to session_metadata. Re-deriving it anywhere else is how two
        # parts of this system end up disagreeing about what the candidate asked for — the
        # bug class that made a sales interview greet somebody as an Accenture ASE.
        src = inspect.getsource(orch._candidate_focus_block)
        assert 'meta.get("focus")' in src

    def test_a_blank_box_does_not_render_an_empty_quotation(self):
        # A model handed `They typed: ""` treats the empty string as a statement. The blank
        # case has to say what it means.
        class _Session:
            session_metadata: dict = {}

        out = orch._candidate_focus_block(_Session())  # type: ignore[arg-type]
        assert "blank" in out
        assert '""' not in out

    def test_a_missing_metadata_row_is_the_same_as_a_blank_box(self):
        class _Session:
            session_metadata = None

        assert "blank" in orch._candidate_focus_block(_Session())  # type: ignore[arg-type]
