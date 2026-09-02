"""
The rubric a deck is judged against — services/deck/criteria.py

ONE SOURCE FOR THE CRITERIA, and it is here rather than in the prompt file because three
things need to agree about them: the prompt that asks for the scores, the schema that
validates what comes back, and the weighting that turns nine numbers into one. A rubric
written only in Markdown cannot be validated against, and one written only in Python cannot
be shown to the model.

WEIGHTS ARE PERCENTAGE POINTS AND THEY MUST TOTAL 100. `total_weight` is asserted by a test
rather than trusted, because the source this rubric was ported from summed to 105 — so a
perfect deck scored 105.00 and every number the product showed was a percentage of nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The criterion graded by `format_grader.py` rather than by the model.
#:
#: Named here so the scoring pass can substitute a measured value for the model's guess.
#: Typography is not a judgement call — the font sizes either are consistent or they are
#: not — and asking a language model to estimate what a parser can read exactly is both
#: more expensive and less accurate.
FORMAT_CRITERION = "format_and_design"


@dataclass(frozen=True, slots=True)
class Criterion:
    """One row of the rubric."""

    key: str
    label: str
    weight: int
    max_score: int = 10

    @property
    def range_text(self) -> str:
        return f"1-{self.max_score}"


#: WHAT A DECK IS SCORED ON, in the order it is shown to the model and to the candidate.
#:
#: Nine criteria at ten points each, weighted to 100. The weights are the ported rubric's,
#: renormalised: technical readiness is the heaviest because it is the thing a deck is most
#: often thinnest on, and presentation and format together are 10 because a beautiful deck
#: with nothing behind it should not out-score a plain one that has done the work.
CRITERIA: tuple[Criterion, ...] = (
    Criterion("problem_understanding", "Problem identification & depth of understanding", 10),
    Criterion("user_centricity", "User-centric approach", 10),
    Criterion("innovation", "Innovation quotient", 15),
    Criterion("technical_readiness", "Technical readiness & prototype potential", 20),
    Criterion("market_potential", "Market potential & scalability", 15),
    Criterion("impact", "Social, economic & environmental impact", 10),
    Criterion("research_depth", "Research depth & ecosystem awareness", 10),
    Criterion("presentation", "Presentation & communication of the idea", 5),
    Criterion(FORMAT_CRITERION, "Format & design of the deck", 5),
)

CRITERIA_BY_KEY: dict[str, Criterion] = {c.key: c for c in CRITERIA}


def total_weight() -> int:
    """Sum of every weight. A perfect deck scores exactly this; a test pins it at 100."""
    return sum(c.weight for c in CRITERIA)


def criteria_block() -> str:
    """The criteria as prompt text: one line per criterion, with its key and range."""
    return "\n".join(
        f"- `{c.key}` — {c.label} (integer {c.range_text}, weight {c.weight}%)"
        for c in CRITERIA
    )


def weighted_total(scores: dict[str, int]) -> float:
    """
    The single number, as a percentage.

    Each criterion is normalised by its own maximum before being weighted, so a rubric
    whose criteria have different maxima still totals 100. A missing criterion scores zero
    rather than being skipped: skipping it would silently raise everything else's share and
    make an incomplete answer look like a good one.
    """
    total = 0.0
    for criterion in CRITERIA:
        raw = scores.get(criterion.key)
        if raw is None:
            continue
        clamped = max(0, min(criterion.max_score, int(raw)))
        total += (clamped / criterion.max_score) * criterion.weight
    return round(total, 2)


def clamp_scores(scores: dict[str, int]) -> dict[str, int]:
    """
    Only known criteria, each inside its own range.

    THE MODEL'S NUMBERS ARE NOT TRUSTED TO BE IN RANGE. It is asked for 1-10 and mostly
    obliges, but an 11 or a 0 arriving occasionally is exactly the kind of thing that
    turns into a weighted total above 100 on somebody's report months later.
    """
    out: dict[str, int] = {}
    for key, value in (scores or {}).items():
        criterion = CRITERIA_BY_KEY.get(key)
        if criterion is None:
            continue
        try:
            numeric = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        out[key] = max(1, min(criterion.max_score, numeric))
    return out
