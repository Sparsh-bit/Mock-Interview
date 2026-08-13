"""
Declining a topic takes it out of the rest of the interview — tests/test_declined_topic_pruning.py

REPORTED: "i want the ai to not to run on a roadmap what it has build ... if someone said that
he don't know any of the topic then the question must not come from their".

That was a precise description of a real gap. A decline already did three things — dont_know.py
detected it server-side, the panel pivoted and offered another topic out loud, and the pivot was
recorded so declining could not be farmed for easier questions. What none of it did was change
which questions came NEXT: the plan is built up front and walked in order, so the candidate was
asked about the same topic again two questions later. Every part of the pivot worked except the
part that made it mean anything.

The DB reads are stubbed rather than mocked against Postgres because what is being tested is the
DECISION — which questions come out, and the two cases where none should.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.interview.orchestrator import InterviewOrchestrator


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _StubDB:
    """Answers `scalars()` from a queue, in call order: answered ids, then same-topic ids."""

    def __init__(self, *results):
        self._queue = list(results)
        self.calls = 0

    async def scalars(self, _stmt):
        self.calls += 1
        return _Result(self._queue.pop(0) if self._queue else [])


class _Session:
    def __init__(self):
        self.id = uuid.uuid4()
        self.track_id = uuid.uuid4()


class _Question:
    def __init__(self, topic_id):
        self.id = uuid.uuid4()
        self.topic_id = topic_id


def _orchestrator(db):
    o = InterviewOrchestrator.__new__(InterviewOrchestrator)
    o.db = db
    return o


@pytest.mark.asyncio
class TestTheDeclinedTopicLeavesThePlan:
    async def test_remaining_questions_on_that_topic_are_dropped(self):
        topic = uuid.uuid4()
        q1, q2, q3, q4 = (str(uuid.uuid4()) for _ in range(4))
        # q1 answered (the decline itself); q2 and q4 are the same topic and still to come.
        db = _StubDB([q1], [q2, q4])
        meta = {"planned_question_ids": [q1, q2, q3, q4]}

        dropped = await _orchestrator(db)._drop_declined_topic(
            _Session(), _Question(topic), meta
        )

        assert dropped == 2
        # The answered one STAYS: the plan is also the record of what was asked.
        assert meta["planned_question_ids"] == [q1, q3]

    async def test_the_topic_is_remembered_so_a_top_up_cannot_restore_it(self):
        topic = uuid.uuid4()
        q1, q2 = str(uuid.uuid4()), str(uuid.uuid4())
        db = _StubDB([], [q1])
        meta = {"planned_question_ids": [q1, q2]}

        await _orchestrator(db)._drop_declined_topic(_Session(), _Question(topic), meta)
        assert meta["declined_topic_ids"] == [str(topic)]

    async def test_declines_on_two_topics_accumulate(self):
        first, second = uuid.uuid4(), uuid.uuid4()
        a, b, c = (str(uuid.uuid4()) for _ in range(3))
        meta = {"planned_question_ids": [a, b, c], "declined_topic_ids": [str(first)]}

        db = _StubDB([], [b])
        await _orchestrator(db)._drop_declined_topic(_Session(), _Question(second), meta)

        # Replacing rather than adding would quietly re-open the first topic to the top-up.
        assert set(meta["declined_topic_ids"]) == {str(first), str(second)}


@pytest.mark.asyncio
class TestItRefusesToEndTheInterviewOnAnAdmission:
    async def test_the_last_remaining_question_is_never_dropped(self):
        # Pruning to nothing would end the interview at the exact moment the candidate
        # admitted a gap, which reads as a punishment for honesty.
        topic = uuid.uuid4()
        answered, last = str(uuid.uuid4()), str(uuid.uuid4())
        db = _StubDB([answered], [last])
        meta = {"planned_question_ids": [answered, last]}

        dropped = await _orchestrator(db)._drop_declined_topic(
            _Session(), _Question(topic), meta
        )

        assert dropped == 0
        assert meta["planned_question_ids"] == [answered, last]

    async def test_nothing_happens_when_no_planned_question_shares_the_topic(self):
        q1, q2 = str(uuid.uuid4()), str(uuid.uuid4())
        db = _StubDB([], [])  # nothing answered, nothing matching
        meta = {"planned_question_ids": [q1, q2]}

        assert await _orchestrator(db)._drop_declined_topic(
            _Session(), _Question(uuid.uuid4()), meta
        ) == 0
        assert meta["planned_question_ids"] == [q1, q2]
        assert "declined_topic_ids" not in meta

    async def test_a_question_with_no_topic_prunes_nothing(self):
        # Generated questions can arrive without a topic. Treating None as a topic would
        # match every other topicless question and gut the plan.
        db = _StubDB()
        meta = {"planned_question_ids": [str(uuid.uuid4()), str(uuid.uuid4())]}
        assert await _orchestrator(db)._drop_declined_topic(
            _Session(), _Question(None), meta
        ) == 0
        assert db.calls == 0, "it should not even query"

    async def test_an_adaptive_session_with_no_plan_is_untouched(self):
        db = _StubDB()
        meta: dict = {}
        assert await _orchestrator(db)._drop_declined_topic(
            _Session(), _Question(uuid.uuid4()), meta
        ) == 0
        assert meta == {}
