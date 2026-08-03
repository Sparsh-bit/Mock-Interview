"""
Interview Rating — services/progress/rating.py

WHAT THIS IS FOR. LeetCode works as a credential because "412 solved, 180 medium"
is a number other people trust, and it is trustworthy for one reason: you cannot
half-solve a problem. Hidden tests pass or they do not. The number therefore
measures something, so chasing it is the same thing as getting better.

An interview simulator cannot copy that directly, because a mock interview has no
pass/fail — it has a score out of 100, and a score out of 100 that only ever goes
up is a participation trophy. Give twenty lazy interviews and the number says the
same thing as twenty good ones.

So there are TWO numbers here, doing two different jobs, which is how every
competitive platform that actually works is built:

  CLEARED ROUNDS — monotonic, never falls. The LeetCode "solved" analogue: a round
  counts as cleared when the report meets the bar for its tier. This is the
  credential you show someone. Split by tier, because "14 cleared" means nothing
  if they were all Foundation.

  RATING — a skill estimate that CAN fall. This is what makes the thing hard, and
  it is the number with the anti-farming properties below.

THE ANTI-FARMING PROPERTY IS THE WHOLE POINT, and it is not a rule bolted on — it
falls out of using an Elo expectation. Your expected score rises with your rating,
so once you are well above a tier's difficulty, clearing it perfectly earns almost
nothing. Grinding the easy set stops paying by construction rather than because a
cap said so. And the same maths is what makes it FAIR: a candidate who genuinely
answers a Panel round well is beating a high expectation and climbs fast. Nobody is
throttled for being good — they are throttled for repeating what they have already
proved.

Two explicit dampers sit on top, and both scale GAIN ONLY, never loss. Practising
must never be punished; it just stops paying above a point.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: Where everyone starts. Chosen so the first few rounds move the number visibly —
#: a ladder whose first rung takes a week to reach is a ladder nobody climbs.
BASE_RATING = 1200

#: Nobody drops below this. A floor exists because the number is meant to make
#: people come back, and a rating in free fall after two bad days does the
#: opposite. Losses are also capped per round (MAX_LOSS) for the same reason.
RATING_FLOOR = 800

#: Most a single round can take away. One disastrous session — a broken mic, a
#: topic they had not opened yet — must not erase a fortnight.
MAX_LOSS = 40


class Tier(StrEnum):
    """
    How hard the round was. Drives both the clear bar and the Elo expectation.

    Derived from the round rather than chosen by the candidate, so it cannot be
    understated to farm an easier expectation.
    """

    FOUNDATION = "foundation"
    CORE = "core"
    PANEL = "panel"


@dataclass(frozen=True)
class TierSpec:
    #: The rating a candidate would need for this tier to be an even match. A round
    #: is "an opponent" with a fixed strength.
    difficulty: int
    #: Report score out of 100 at or above which the round counts as CLEARED.
    #: Rises with tier: clearing Panel has to mean more than clearing Foundation,
    #: or the ledger is just a session count with extra words.
    clear_bar: int
    label: str


TIERS: dict[Tier, TierSpec] = {
    Tier.FOUNDATION: TierSpec(difficulty=1100, clear_bar=65, label="Foundation"),
    Tier.CORE: TierSpec(difficulty=1450, clear_bar=72, label="Core"),
    Tier.PANEL: TierSpec(difficulty=1800, clear_bar=78, label="Panel"),
}


@dataclass(frozen=True)
class Rank:
    floor: int
    name: str
    #: One line on what the rank actually claims about the candidate. Shown in the
    #: UI, because "Shortlisted" on its own is a word, not a signal.
    meaning: str


#: The ladder. Named for what a campus candidate is actually chasing — a seat in
#: the room, then an offer — rather than metals, because "Gold III" means nothing
#: to somebody preparing for a Cognizant drive.
RANKS: list[Rank] = [
    Rank(0, "Aspirant", "Getting your bearings. Every round from here moves the number."),
    Rank(1200, "Shortlisted", "You would clear a résumé screen and hold a basic round."),
    Rank(1400, "Interview Ready", "You handle a standard GenC Next round without falling apart."),
    Rank(1600, "Offer Ready", "You hold up under cross-questioning on your own answers."),
    Rank(1800, "Top of Batch", "You clear Panel rounds. Very few people in a batch are here."),
    Rank(2000, "Placement Elite", "You would be the strongest candidate in most rooms."),
]


def rank_for(rating: int) -> Rank:
    """The highest rank whose floor this rating has reached."""
    current = RANKS[0]
    for r in RANKS:
        if rating >= r.floor:
            current = r
    return current


def next_rank(rating: int) -> Rank | None:
    """The next rung, or None at the top."""
    for r in RANKS:
        if r.floor > rating:
            return r
    return None


def k_factor(rated_rounds: int) -> int:
    """
    How much one round is allowed to move the rating.

    Large while we still know nothing, small once the estimate has settled — the
    standard provisional-rating idea, and it matters here for a product reason as
    much as a statistical one: a first-timer must see the number move, and someone
    forty rounds in must not be able to swing it back and forth on a whim.
    """
    if rated_rounds < 5:
        return 80
    if rated_rounds < 15:
        return 48
    return 32


def expected_score(rating: int, difficulty: int) -> float:
    """
    Standard Elo expectation: how well someone at `rating` should do against a round
    of this `difficulty`, as 0-1.

    This one function is the anti-farming engine. At rating 1800 against Foundation
    (1100) the expectation is ~0.98, so a flawless Foundation round pays about two
    percent of a K-factor — a couple of points. The candidate is not being punished;
    they are being told they already proved this. The only way up is a harder tier.
    """
    return 1.0 / (1.0 + 10 ** ((difficulty - rating) / 400))


def performance(score_out_of_100: float) -> float:
    """
    The report score as an Elo "result", 0-1.

    Deliberately NOT a straight score/100. A 50 is not "half a win" in an interview
    — it is a fail that an interviewer would not call back. The midpoint of the
    result scale is placed at 70, the level a real panel treats as acceptable, so
    scoring 60 loses ground against an even match rather than treading water.
    Below 30 and above 95 are flattened, because the difference between a 10 and a
    20 is noise about how badly it went.
    """
    s = max(0.0, min(100.0, float(score_out_of_100)))
    if s <= 30:
        return 0.0
    if s >= 95:
        return 1.0
    # Two straight segments meeting at (70, 0.5).
    if s <= 70:
        return (s - 30) / 40 * 0.5
    return 0.5 + (s - 70) / 25 * 0.5


#: Gain multiplier when the round mostly re-covers topics already answered. Loss is
#: never scaled — see gain_scale.
_REPEAT_SCALE_FLOOR = 0.25

#: After this many rated rounds in one day, further gain is damped. Not blocked:
#: somebody cramming the night before a drive should be able to keep practising,
#: they just cannot inflate a credential in an evening.
_ROUNDS_PER_DAY_FREE = 2
_DAILY_SCALE_FLOOR = 0.3


def gain_scale(topic_overlap: float, rounds_today: int) -> float:
    """
    How much of a positive delta actually lands.

    Applied to GAIN ONLY. Scaling losses too would mean a candidate who practises a
    lot is penalised less for a bad round than someone who practises rarely, which
    is both unfair and exactly backwards as an incentive.

    `topic_overlap` is 0-1: the share of this round's topics the candidate has
    already been scored on. Answering the same eight questions a fifth time is
    revision, and revision is good for them but it is not new evidence, so it must
    not move a number other people are meant to trust.
    """
    overlap = max(0.0, min(1.0, topic_overlap))
    repeat = 1.0 - overlap * (1.0 - _REPEAT_SCALE_FLOOR)

    extra = max(0, rounds_today - _ROUNDS_PER_DAY_FREE)
    daily = max(_DAILY_SCALE_FLOOR, 1.0 / (1.0 + 0.5 * extra))

    return repeat * daily


@dataclass(frozen=True)
class RatingOutcome:
    delta: int
    rating_after: int
    cleared: bool
    expected: float
    actual: float
    #: What fraction of the raw gain survived the dampers, for the "why did I only
    #: get 2 points" explanation the UI owes the candidate.
    applied_scale: float


def rate_round(
    *,
    rating: int,
    rated_rounds: int,
    tier: Tier,
    score_out_of_100: float,
    topic_overlap: float = 0.0,
    rounds_today: int = 0,
) -> RatingOutcome:
    """
    Score one completed round.

    Pure, so the properties that make the credential worth chasing — that grinding
    an easy tier converges to nothing, that a strong Panel round pays a lot, that
    the number cannot be inflated in an evening — are testable rather than hoped
    for. Nothing here touches the database.
    """
    spec = TIERS[tier]
    exp = expected_score(rating, spec.difficulty)
    act = performance(score_out_of_100)
    raw = k_factor(rated_rounds) * (act - exp)

    scale = gain_scale(topic_overlap, rounds_today) if raw > 0 else 1.0
    delta = raw * scale

    # Round away from zero so a genuine (if small) gain never silently disappears —
    # "you gained 0" reads as broken. A raw delta that IS effectively zero stays zero.
    if 0 < delta < 1:
        delta = 1.0
    elif -1 < delta < 0:
        delta = -1.0

    delta_i = int(round(delta))
    if delta_i < -MAX_LOSS:
        delta_i = -MAX_LOSS

    after = max(RATING_FLOOR, rating + delta_i)
    # The floor can absorb part of a loss; report the delta that actually happened.
    delta_i = after - rating

    return RatingOutcome(
        delta=delta_i,
        rating_after=after,
        cleared=score_out_of_100 >= spec.clear_bar,
        expected=round(exp, 4),
        actual=round(act, 4),
        applied_scale=round(scale, 4),
    )


def tier_for(
    *,
    question_count: int,
    company_difficulty: str | None,
    had_cross_questions: bool,
) -> Tier:
    """
    Which tier a round was, from the round itself.

    Derived rather than chosen, so a candidate cannot declare a full Panel round to
    be Foundation and farm the easier expectation. Cross-questions are the strongest
    single signal — being made to defend your own answer is what separates a real
    panel from a quiz — followed by length.
    """
    difficulty = (company_difficulty or "").strip().lower()

    if had_cross_questions and question_count >= 12:
        return Tier.PANEL
    if difficulty in {"hard", "very hard", "advanced"} and question_count >= 10:
        return Tier.PANEL
    if question_count < 6:
        return Tier.FOUNDATION
    if difficulty in {"easy", "beginner"} and not had_cross_questions:
        return Tier.FOUNDATION
    return Tier.CORE
