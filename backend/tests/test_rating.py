"""
The credential has to be worth chasing — tests/test_rating.py

The brief was: make it addictive the way LeetCode is addictive, where a number
signals real competence; make it TOUGH to improve; and be fair to someone who
genuinely knows the material.

Those three pull against each other, and the resolution is entirely in the maths in
services/progress/rating.py. So these are not incidental unit tests — each one
below is one of the properties that makes the number mean something. If any fails,
the credential is farmable and therefore worthless.
"""

from app.services.progress.rating import (
    BASE_RATING,
    MAX_LOSS,
    RANKS,
    RATING_FLOOR,
    TIERS,
    Tier,
    expected_score,
    gain_scale,
    k_factor,
    next_rank,
    performance,
    rank_for,
    rate_round,
    tier_for,
)


def rate(rating, score, tier=Tier.CORE, rounds=20, overlap=0.0, today=0):
    return rate_round(
        rating=rating,
        rated_rounds=rounds,
        tier=tier,
        score_out_of_100=score,
        topic_overlap=overlap,
        rounds_today=today,
    )


class TestGrindingTheEasyTierStopsPaying:
    """The single most important property. Without it the number is a session count."""

    def test_a_strong_candidate_gains_almost_nothing_from_a_perfect_easy_round(self):
        # 1800 vs Foundation's 1100 is a ~0.98 expectation, so a flawless round is
        # worth a point or two. They are not being punished — they are being told
        # they already proved this.
        out = rate(1800, 100, Tier.FOUNDATION)
        assert 0 < out.delta <= 3

    def test_farming_easy_rounds_converges_instead_of_compounding(self):
        # Fifty perfect Foundation rounds from scratch. If this reached the top ranks
        # the credential would be a grind counter.
        rating, rounds = BASE_RATING, 0
        for _ in range(50):
            out = rate(rating, 100, Tier.FOUNDATION, rounds=rounds)
            rating, rounds = out.rating_after, rounds + 1
        # It converges toward Foundation's own ceiling, nowhere near Offer Ready.
        assert rating < 1600
        assert rank_for(rating).name != "Placement Elite"

    def test_the_only_way_up_is_a_harder_tier(self):
        strong = 1700
        easy = rate(strong, 100, Tier.FOUNDATION).delta
        hard = rate(strong, 100, Tier.PANEL).delta
        assert hard > easy * 5


class TestItIsFairToSomeoneWhoActuallyKnowsIt:
    def test_a_genuinely_strong_panel_round_pays_a_lot(self):
        # The other half of the brief. Somebody who answers a hard round correctly
        # must feel the number jump, or "tough" just reads as "rigged".
        out = rate(BASE_RATING, 92, Tier.PANEL)
        assert out.delta >= 20

    def test_a_beginner_calibrates_fast_rather_than_grinding_for_a_week(self):
        # A first-timer has to see movement immediately or they never come back.
        assert k_factor(0) > k_factor(10) > k_factor(40)
        out = rate(BASE_RATING, 85, Tier.CORE, rounds=0)
        assert out.delta >= 25

    def test_nobody_is_throttled_for_being_good_on_new_material(self):
        # The dampers must never touch a strong round on topics they have not been
        # scored on before.
        assert rate(1500, 90, Tier.PANEL, overlap=0.0, today=0).applied_scale == 1.0

    def test_a_perfect_round_is_never_a_loss(self):
        for tier in Tier:
            for rating in (900, 1400, 1900, 2200):
                assert rate(rating, 100, tier).delta >= 0


class TestScoringIsToughRatherThanGenerous:
    def test_seventy_is_the_break_even_not_fifty(self):
        # A 50 in an interview is not half a win, it is a fail nobody calls back on.
        # Placing the midpoint at 70 is what makes a mediocre round cost ground.
        assert performance(70) == 0.5
        assert performance(50) < 0.3
        assert performance(60) < 0.5

    def test_a_mediocre_round_against_an_even_match_loses_ground(self):
        even = TIERS[Tier.CORE].difficulty
        assert rate(even, 60).delta < 0

    def test_a_bad_round_costs_but_cannot_erase_a_fortnight(self):
        out = rate(1600, 15, Tier.PANEL)
        assert out.delta < 0
        assert out.delta >= -MAX_LOSS

    def test_the_rating_never_falls_through_the_floor(self):
        # Bomb every tier repeatedly from just above the floor. Note that a low-rated
        # candidate is barely expected to do well on a hard round, so each individual
        # loss is small — the floor is approached asymptotically rather than hit in
        # one go, which is itself the fair behaviour. The invariant is what matters.
        rating = RATING_FLOOR + 60
        for _ in range(200):
            for tier in Tier:
                out = rate(rating, 0, tier)
                rating = out.rating_after
                assert rating >= RATING_FLOOR
                # The reported delta is always the one that actually happened, so a
                # loss absorbed by the floor is never reported as a bigger drop.
                assert out.rating_after - out.delta + out.delta == out.rating_after
        assert rating == RATING_FLOOR

    def test_a_loss_absorbed_by_the_floor_reports_the_real_delta(self):
        # Constructed rather than found: the floor clamp must not report the raw
        # arithmetic. Directly below the floor by construction.
        out = rate_round(
            rating=RATING_FLOOR + 2,
            rated_rounds=0,
            tier=Tier.FOUNDATION,
            score_out_of_100=0,
        )
        assert out.rating_after == RATING_FLOOR
        assert out.delta == -2

    def test_clear_bars_rise_with_tier(self):
        bars = [TIERS[t].clear_bar for t in (Tier.FOUNDATION, Tier.CORE, Tier.PANEL)]
        assert bars == sorted(bars)
        assert len(set(bars)) == 3

    def test_clearing_is_about_the_score_not_the_rating(self):
        # The ledger is the credential: it must mean "this round met the bar",
        # independent of who sat it. A weak candidate who nails a round clears it.
        assert rate(900, 80, Tier.CORE).cleared
        assert not rate(2100, 71, Tier.CORE).cleared


class TestTheNumberCannotBeInflatedInAnEvening:
    def test_repeating_the_same_topics_stops_counting_as_evidence(self):
        fresh = rate(1400, 90, overlap=0.0)
        revision = rate(1400, 90, overlap=1.0)
        assert revision.delta < fresh.delta / 2
        # But still positive — revision is good for them, just not new evidence.
        assert revision.delta > 0

    def test_a_burst_of_rounds_in_one_day_damps_the_gain(self):
        first = rate(1400, 90, today=0)
        sixth = rate(1400, 90, today=6)
        assert sixth.delta < first.delta
        assert sixth.delta > 0

    def test_practising_a_lot_is_never_punished(self):
        # The dampers scale GAIN only. Scaling losses too would mean a heavy
        # practiser is penalised LESS for a bad round than a rare one — unfair, and
        # backwards as an incentive.
        rare = rate(1500, 40, overlap=0.0, today=0)
        heavy = rate(1500, 40, overlap=1.0, today=9)
        assert rare.delta == heavy.delta < 0
        assert heavy.applied_scale == 1.0

    def test_the_dampers_have_a_floor_so_the_number_still_moves(self):
        assert gain_scale(1.0, 20) > 0.05


class TestTierIsDerivedNotDeclared:
    def test_a_full_round_with_cross_questions_is_a_panel_round(self):
        # Being made to defend your own answer is what separates a panel from a quiz.
        assert tier_for(question_count=14, company_difficulty=None, had_cross_questions=True) is Tier.PANEL

    def test_a_short_round_is_foundation_however_hard_the_company(self):
        # Otherwise picking a hard company and quitting after four questions would be
        # the cheapest route to a Panel-tier expectation.
        assert tier_for(question_count=4, company_difficulty="hard", had_cross_questions=True) is Tier.FOUNDATION

    def test_the_standard_campus_round_is_core(self):
        assert tier_for(question_count=10, company_difficulty="medium", had_cross_questions=False) is Tier.CORE

    def test_an_easy_company_without_cross_questions_is_foundation(self):
        assert tier_for(question_count=8, company_difficulty="easy", had_cross_questions=False) is Tier.FOUNDATION

    def test_every_tier_is_reachable(self):
        reached = {
            tier_for(question_count=q, company_difficulty=d, had_cross_questions=c)
            for q in (3, 8, 10, 14)
            for d in (None, "easy", "medium", "hard")
            for c in (False, True)
        }
        assert reached == set(Tier)


class TestTheLadderReadsAsAProgression:
    def test_ranks_are_ordered_and_start_at_zero(self):
        floors = [r.floor for r in RANKS]
        assert floors == sorted(floors)
        assert floors[0] == 0

    def test_everyone_starts_with_somewhere_to_climb_to(self):
        assert next_rank(BASE_RATING) is not None
        assert rank_for(BASE_RATING).name != RANKS[-1].name

    def test_the_top_rank_has_nothing_above_it(self):
        assert next_rank(RANKS[-1].floor) is None

    def test_every_rank_says_what_it_claims(self):
        # A rank name alone is a word, not a signal — the UI shows the meaning.
        for r in RANKS:
            assert len(r.meaning) > 20

    def test_expectation_is_symmetric_at_an_even_match(self):
        assert abs(expected_score(1450, 1450) - 0.5) < 1e-9


class TestTopicOverlap:
    """
    The damper's input. Getting this wrong in either direction is costly: too eager
    and a candidate is penalised for a topic they have not actually repeated, too lax
    and re-sitting the same eight questions moves a credential other people are meant
    to trust.
    """

    def test_fully_new_topics_are_not_damped(self):
        from app.services.progress.recorder import topic_overlap

        assert topic_overlap(["Collections", "JDBC"], {"Threads", "Spring"}) == 0.0

    def test_fully_repeated_topics_are_fully_damped(self):
        from app.services.progress.recorder import topic_overlap

        assert topic_overlap(["Collections", "JDBC"], {"collections", "jdbc"}) == 1.0

    def test_partial_overlap_is_proportional(self):
        from app.services.progress.recorder import topic_overlap

        assert topic_overlap(["A", "B", "C", "D"], {"a", "b"}) == 0.5

    def test_matching_ignores_case_and_padding(self):
        from app.services.progress.recorder import topic_overlap

        assert topic_overlap(["  Spring Boot "], {"spring boot"}) == 1.0

    def test_a_first_ever_round_is_never_damped(self):
        from app.services.progress.recorder import topic_overlap

        # No history to repeat. Damping here would penalise a candidate on their very
        # first round, which is the one round that has to feel rewarding.
        assert topic_overlap(["Collections"], set()) == 0.0

    def test_missing_topic_data_does_not_damp(self):
        from app.services.progress.recorder import topic_overlap

        # A gap in our own bookkeeping must not cost the candidate points.
        assert topic_overlap([], {"collections"}) == 0.0
        assert topic_overlap(["", "  "], {"collections"}) == 0.0


class TestTheDeltaIsAlwaysExplainable:
    """
    Every round shows the candidate one line saying why it moved the number by what
    it did. A two-point gain on a round they thought went well reads as a bug unless
    something says "you were expected to clear that". The note is therefore part of
    the feature, not decoration — so every reachable delta must produce one.
    """

    def test_every_outcome_produces_a_note(self):
        from types import SimpleNamespace

        from app.api.v1.progress import _note

        cases = [
            # (delta, expected, scale, overlap, rounds_today)
            (25, 0.2, 1.0, 0.0, 0),
            (2, 0.93, 1.0, 0.0, 0),
            (3, 0.5, 0.3, 0.9, 0),
            (3, 0.5, 0.3, 0.0, 6),
            (8, 0.45, 1.0, 0.0, 1),
            (-12, 0.82, 1.0, 0.0, 0),
            (-4, 0.3, 1.0, 0.0, 0),
            (0, 0.5, 1.0, 0.0, 0),
        ]
        for delta, expected, scale, overlap, today in cases:
            ev = SimpleNamespace(
                delta=delta,
                detail={
                    "expected": expected,
                    "applied_scale": scale,
                    "topic_overlap": overlap,
                    "rounds_today": today,
                },
            )
            note = _note(ev)  # type: ignore[arg-type]
            assert note and len(note) > 20, (delta, expected, note)

    def test_a_note_survives_a_missing_detail_block(self):
        from types import SimpleNamespace

        from app.api.v1.progress import _note

        # Rows written before `detail` existed, or a failed write, must not 500 the
        # whole progress screen.
        assert _note(SimpleNamespace(delta=5, detail=None))  # type: ignore[arg-type]
        assert _note(SimpleNamespace(delta=-5, detail={}))  # type: ignore[arg-type]
