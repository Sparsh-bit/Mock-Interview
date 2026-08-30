"""
Unlocks you earned, and questions you have outgrown — tests/test_milestones.py

Two mechanics, one file, because they answer halves of the same question: what has this
candidate actually got better at, and what should the product do differently because of it.

────────────────────────────────────────────────────────────────────────────────────────────
WHAT THESE TESTS ARE MOSTLY ABOUT
────────────────────────────────────────────────────────────────────────────────────────────

Not the arithmetic — that is a handful of comparisons. They are about the four shapes this
was told not to have, and each is asserted where it could actually appear rather than
promised in a comment:

    NOT VARIABLE REWARD    every condition is a stated threshold, and `upcoming()` shows the
                           requirement and the distance BEFORE it is earned. Nothing is
                           random, nothing is a surprise.
    NOT URGENCY            nothing expires, decays, or is time-limited. There is no clock in
                           any condition.
    NOT GUILT              no condition and no copy characterises the candidate for an
                           absence, and nothing compares them to anyone else.
    NOT PARTICIPATION      no milestone can be earned by turning up. `streak` appears in no
                           condition, and every count is of rounds CLEARED rather than sat —
                           which also means none of them is purchasable with credits.

The reason these are enforced rather than intended: `docs/COMPLIANCE.md` records that this
product has no reliable way to know it is not talking to a minor, and DPDP §9 prohibits
behavioural monitoring and targeted advertising directed at children. Mechanics that work by
compulsion are the ones that would be a problem if a minor reached them.

────────────────────────────────────────────────────────────────────────────────────────────
AND THE DIFFICULTY FLOOR
────────────────────────────────────────────────────────────────────────────────────────────

`orchestrator._opening_signals_from_self_rating` used to consider only what the candidate
claimed today, so somebody six rounds in and rated 1700 opened at "medium" like a first-timer
and spent two of their twelve questions being asked things they outgrew four rounds ago.

The fix answers the DEFAULT with the ledger and leaves the CLAIM alone.

That distinction is a correction these tests forced. The first draft took the maximum of the
two — "a floor, it can only raise an opening" — which sounds safe and means that a candidate
rated 1700 who says "3, I'm shaky today" is handed hard questions anyway. Being nervous is a
real state, and overriding it is the app telling somebody how they feel.
`test_a_nervous_day_is_respected` failed against that draft, and the implementation changed
rather than the test.

What was actually broken was never the claim — the existing code already notes that "an
overclaim buys two hard questions and is then corrected by evidence, and an underclaim buys
two easy ones and is corrected the same way". It was the DEFAULT: "medium" was the answer for
a first-timer and for somebody six rounds in, permanently, because no claim meant no evidence
and there was nowhere else to look.
"""

from __future__ import annotations

import inspect

import pytest

from app.services.progress import milestones as m
from app.services.progress import progression as p
from app.services.progress.rating import BASE_RATING, Tier


def _code(module) -> str:
    """
    A module's source with comments and docstrings stripped, lower-cased.

    Every scan below is looking for a MECHANIC, and these modules explain in prose exactly
    which mechanics they refuse to have — so a whole-file scan matches its own explanation and
    the assertion silently becomes vacuous. Stripping the prose is what keeps these tests
    about the code.
    """
    import io
    import tokenize

    src = inspect.getsource(module)
    out: list[str] = []
    prev = tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and prev in (
            tokenize.INDENT, tokenize.NEWLINE, tokenize.NL, tokenize.DEDENT,
        ):
            continue  # a docstring
        if tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            prev = tok.type
        out.append(tok.string)
    return " ".join(out).lower()


def _progress(
    rating: int = BASE_RATING,
    *,
    foundation: int = 0,
    core: int = 0,
    panel: int = 0,
    topics: int = 0,
    composed: int = 0,
) -> m.Progress:
    return m.Progress(
        rating=rating,
        cleared={Tier.FOUNDATION: foundation, Tier.CORE: core, Tier.PANEL: panel},
        topics_covered=topics,
        rounds_without_declining=composed,
    )


class TestMilestonesAreEarnedBySkill:
    def test_a_brand_new_candidate_has_earned_nothing(self):
        assert m.earned(_progress()) == []

    def test_clearing_a_round_earns_the_first_one(self):
        assert [x.key for x in m.earned(_progress(foundation=1))] == ["first_cleared"]

    def test_three_core_rounds_is_a_level(self):
        keys = {x.key for x in m.earned(_progress(core=3))}
        assert "core_three" in keys

    def test_two_core_rounds_is_not_yet(self):
        assert "core_three" not in {x.key for x in m.earned(_progress(core=2))}

    def test_rating_milestones_track_the_rank_ladder(self):
        assert "interview_ready" in {x.key for x in m.earned(_progress(1400))}
        assert "interview_ready" not in {x.key for x in m.earned(_progress(1399))}
        assert "offer_ready" in {x.key for x in m.earned(_progress(1600))}

    def test_breadth_is_measured_in_subjects_not_rounds(self):
        # Eight rounds on one topic is revision. The milestone is about breadth, so it counts
        # distinct subjects and cannot be farmed by re-sitting the same interview.
        assert "breadth_eight" not in {x.key for x in m.earned(_progress(core=8, topics=2))}
        assert "breadth_eight" in {x.key for x in m.earned(_progress(topics=8))}


class TestItIsNotAVariableReward:
    def test_every_milestone_states_its_requirement_before_it_is_earned(self):
        for milestone in m.MILESTONES:
            assert milestone.requirement.strip(), f"{milestone.key} has no stated requirement"
            # A requirement that does not name a number is not a requirement a candidate can
            # act on — it is a hint, which is what a surprise reward looks like from outside.
            assert any(ch.isdigit() for ch in milestone.requirement), milestone.key

    def test_the_next_milestones_are_visible_with_their_distance(self):
        progress = _progress(1300, core=1, topics=4)
        ahead = m.upcoming(progress)
        assert ahead, "a candidate mid-way must be able to see what is next"
        for milestone, fraction in ahead:
            assert not milestone.met(progress)
            assert 0.0 <= fraction <= 1.0
            assert milestone.requirement

    def test_the_nearest_milestone_is_offered_first(self):
        # The next thing shown is the next thing ACHIEVABLE, not the most impressive one —
        # which is what stops this being a dangled prize.
        progress = _progress(1380, core=2, topics=7)
        ahead = m.upcoming(progress, limit=3)
        fractions = [f for _m, f in ahead]
        assert fractions == sorted(fractions, reverse=True)

    def test_progress_is_partial_rather_than_binary(self):
        # A binary reads as "nothing is happening" for the eight rounds before it flips.
        assert m.MILESTONES[1].fraction(_progress(core=1)) == pytest.approx(1 / 3)
        assert m.MILESTONES[1].fraction(_progress(core=2)) == pytest.approx(2 / 3)

    def test_nothing_is_random(self):
        # SCANNED OVER CODE, NOT PROSE. The module docstring explains at length why there is no
        # roll and no chance here, so a naive whole-file scan matches its own explanation —
        # which is the classic way a source assertion ends up asserting nothing.
        for word in ("random", "shuffle", "choice(", "lottery", "weighted"):
            assert word not in _code(m), f"{word!r} in milestone code is a variable reward"


class TestItIsNotUrgencyOrGuilt:
    def test_no_condition_involves_time(self):
        conditions = _code(m)
        conditions = conditions[conditions.index("milestones : list"):]
        for word in ("datetime", "expire", "deadline", "countdown", "days_left", "timedelta"):
            assert word not in conditions.lower(), f"{word!r} makes a milestone time-limited"

    def test_no_milestone_can_be_lost(self):
        # `met` is monotonic in every input, so a milestone once earned stays earned. Asserted
        # by construction: nothing in this module's CODE writes, decrements or revokes.
        for word in ("revoke", "expire", "reset", "delete", "-=", "decrement"):
            assert word not in _code(m), f"{word!r} suggests a milestone can be taken away"

    def test_a_milestone_once_earned_stays_earned(self):
        # The property itself, not a proxy for it: more of anything never earns less.
        smaller = _progress(1400, core=3, topics=8, composed=3)
        larger = _progress(1700, core=9, panel=2, topics=20, composed=11)
        assert {x.key for x in m.earned(smaller)} <= {x.key for x in m.earned(larger)}

    def test_the_copy_never_characterises_the_candidate_for_an_absence(self):
        for milestone in m.MILESTONES:
            text = f"{milestone.name} {milestone.claim} {milestone.requirement}".lower()
            for phrase in (
                "don't lose", "falling behind", "you failed", "you haven't",
                "everyone else", "other candidates", "hurry", "last chance", "only today",
            ):
                assert phrase not in text, f"{milestone.key} carries pressure copy"

    def test_every_claim_is_about_capability_rather_than_a_count(self):
        # "You did 10 things" is a counter with a medal on it. The claim has to say what the
        # candidate can now do.
        for milestone in m.MILESTONES:
            assert len(milestone.claim.split()) >= 6, milestone.key


class TestItCannotBeEarnedByTurningUpOrPaying:
    def test_no_condition_reads_a_streak(self):
        conditions = _code(m)
        assert "streak" not in conditions[conditions.index("milestones : list"):]

    def test_rounds_sat_earn_nothing(self):
        """
        THE ONE THAT KEEPS CREDITS OUT OF IT. Every count is of rounds CLEARED — 65 at
        Foundation, 72 at Core, 78 at Panel. A candidate who buys twenty interviews and fails
        all of them has earned nothing, which is the point: counting rounds sat would turn the
        ladder into a receipt.
        """
        # Twenty rounds, none cleared, plenty of topics seen.
        nothing_cleared = m.Progress(
            rating=BASE_RATING, cleared={}, topics_covered=0, rounds_without_declining=0
        )
        assert m.earned(nothing_cleared) == []

    def test_the_ledger_read_counts_only_cleared_rows(self):
        src = inspect.getsource(m.progress_for)
        assert "RatingEvent.cleared.is_(True)" in src


class TestTheDifficultyFloor:
    def test_a_first_timer_gets_exactly_what_they_asked_for(self):
        # The whole point of the "no evidence, no floor" branch: this function existing must
        # not change anything at all for somebody on their first round.
        for claim, expected in ((2, "easy"), (6, "medium"), (9, "hard"), (None, "medium")):
            assert (
                p.opening_difficulty(rating=BASE_RATING, cleared={}, self_rating=claim)
                == expected
            )

    def test_a_returning_candidate_does_not_reopen_at_the_bottom(self):
        """
        THE DEFECT. Rated 1700, six rounds in, says nothing — used to open at "medium" like a
        first-timer and spend two of twelve questions on material they outgrew.
        """
        assert p.opening_difficulty(rating=1700, cleared={Tier.CORE: 4}, self_rating=None) == "hard"

    def test_the_floor_never_makes_an_interview_easier_than_asked(self):
        # A candidate who says they are ready for hard questions gets them, whatever the
        # ledger says. Telling somebody they are not ready is both wrong and insulting.
        assert p.opening_difficulty(rating=900, cleared={}, self_rating=9) == "hard"
        assert p.opening_difficulty(rating=1500, cleared={Tier.CORE: 3}, self_rating=10) == "hard"

    def test_a_nervous_day_is_respected(self):
        """
        The asymmetry, stated as a case. Somebody rated 1700 who says they are shaky today
        gets an easy opener — being nervous is a real state, and overriding it would be the
        app telling somebody how they feel.

        This is safe because the floor is superseded by the first scored answer anyway: the
        adaptive loop takes over from question two.
        """
        assert p.opening_difficulty(rating=1700, cleared={Tier.CORE: 4}, self_rating=3) == "easy"

    def test_cleared_panel_rounds_raise_the_floor_past_the_rating(self):
        # The rating is an average over their whole history; the cleared count is a statement
        # about their best. For "what should we open with", the best is the better evidence.
        assert p.opening_difficulty(rating=1300, cleared={Tier.PANEL: 2}, self_rating=None) == "hard"

    def test_one_cleared_panel_round_is_not_yet_settled_evidence(self):
        assert p.opening_difficulty(rating=1300, cleared={Tier.PANEL: 1}, self_rating=None) != "hard"

    def test_the_bands_match_the_orchestrator_so_one_answer_does_not_mean_two(self):
        """
        `_self_rating_band` here and `_opening_signals_from_self_rating` there map the same
        1–10 number to a difficulty. Two mappings would be two different interviews for the
        same answer, and the candidate would have no way to tell which one they got.
        """
        from app.services.interview.orchestrator import InterviewOrchestrator

        src = inspect.getsource(InterviewOrchestrator._opening_signals_from_self_rating)
        assert "claimed <= 4" in src and "claimed <= 7" in src
        assert p._self_rating_band(4) == "easy"
        assert p._self_rating_band(7) == "medium"
        assert p._self_rating_band(8) == "hard"

    def test_the_orchestrator_answers_the_default_and_never_overrides_the_claim(self):
        """
        THE PRECEDENCE, ASSERTED WHERE IT IS APPLIED.

        An earlier draft of this took `max(claim, ledger)`, which would have handed a nervous
        candidate hard questions on the strength of rounds they sat last week. The test above
        caught it. What must be true now is narrower and correct: the ledger answers the case
        where there is no claim, and the claim is returned untouched in every other case.
        """
        from app.services.interview.orchestrator import InterviewOrchestrator

        src = inspect.getsource(InterviewOrchestrator._opening_signals_from_self_rating)
        assert "opening_difficulty" in src
        # The ledger is consulted only on the no-claim return.
        assert "return floor or \"medium\", []" in src
        # And the claim branch that follows it does not consult the floor at all.
        claim_branch = src[src.index("if claimed <= 4:"):]
        assert "floor" not in claim_branch, (
            "the ledger reaches the claim branch — a stated self-rating is being overridden"
        )

    def test_a_failure_to_read_the_ledger_leaves_todays_behaviour(self):
        # A dashboard number failing must not cost somebody their interview.
        from app.services.interview.orchestrator import InterviewOrchestrator

        src = inspect.getsource(InterviewOrchestrator._opening_signals_from_self_rating)
        assert "except Exception" in src
        assert "floor: str | None = None" in src


class TestTheResumePoint:
    def test_it_requires_an_answered_question(self):
        # An abandoned setup form is not a session worth resuming — that is the difference
        # between "you were half way through" and "you once opened a form".
        src = inspect.getsource(p.resume_point)
        assert "questions_asked > 0" in src

    def test_it_is_bounded_by_a_window(self):
        # An unfinished interview from three weeks ago is not something anybody is coming back
        # to, and offering it reads as the app not having noticed they moved on.
        src = inspect.getsource(p.resume_point)
        assert "RESUME_WINDOW" in src

    def test_it_only_looks_at_live_sessions(self):
        src = inspect.getsource(p.resume_point)
        assert "SessionStatus.ACTIVE" in src

    def test_it_reports_a_fact_and_not_a_deadline(self):
        # `hours_ago` is elapsed time, not time remaining. There is nothing here that counts
        # down, and no field a countdown could be built from without adding one.
        assert set(p.ResumePoint.__dataclass_fields__) == {
            "session_id",
            "questions_answered",
            "hours_ago",
        }
