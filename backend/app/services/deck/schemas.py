"""Response shapes for the deck evaluator — services/deck/schemas.py"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .criteria import CRITERIA


class DiagramAnalysis(BaseModel):
    """One image, as the vision pass read it."""

    image_index: int = 0
    description: str = ""
    type: str = "Other"
    is_diagram: bool = False
    importance: str = "supporting"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class DiagramReport(BaseModel):
    """What the vision pass saw across the whole deck."""

    overall_summary: str = ""
    image_analyses: list[DiagramAnalysis] = []

    @property
    def diagram_count(self) -> int:
        return sum(1 for a in self.image_analyses if a.is_diagram)


class JudgeResponse(BaseModel):
    """
    Exactly what the judging prompt is asked for, and nothing else.

    NO DEFAULT ON `scores`. `generate_structured` retries on a validation failure, so a
    model that answers without scores gets another attempt — which is the correct outcome
    and is only possible if the absence is invalid. A default of `{}` would make an empty
    answer valid, and the candidate would get a report of zeroes with no error anywhere.
    """

    scores: dict[str, int]
    summary: str = ""


class CriterionScore(BaseModel):
    """One scored criterion, as the API returns it."""

    key: str
    label: str
    score: int
    max_score: int
    weight: int
    #: True when this came from a parser rather than the model. Only the format criterion.
    measured: bool = False


class DeckEvaluation(BaseModel):
    """The full result for one deck."""

    filename: str
    slide_count: int
    weighted_total: float = Field(description="Percentage, 0-100.")
    scores: list[CriterionScore]
    summary: str
    format_notes: list[str] = []
    format_skipped: list[str] = []
    diagram_summary: str = ""
    diagram_count: int = 0
    #: How many slide images the model actually saw. 0 means it scored on text alone.
    images_analysed: int = 0
    #: Set when the deck could not be rasterized, so a text-only score is explained
    #: rather than looking like a complete one.
    vision_unavailable_reason: str | None = None

    @property
    def scored_on_text_alone(self) -> bool:
        return self.images_analysed == 0


def score_rows(
    scores: dict[str, int], *, measured_keys: frozenset[str]
) -> list[CriterionScore]:
    """Turn the score map into ordered rows, in the rubric's own order."""
    return [
        CriterionScore(
            key=c.key,
            label=c.label,
            score=scores.get(c.key, 0),
            max_score=c.max_score,
            weight=c.weight,
            measured=c.key in measured_keys,
        )
        for c in CRITERIA
    ]
