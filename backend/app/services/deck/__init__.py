"""
Deck evaluation: scoring an uploaded pitch deck against a weighted rubric.

`evaluator.DeckEvaluator` is the entry point. The stages are usable on their own —
`format_grader.grade` needs no model and no network at all.
"""

from .criteria import CRITERIA, FORMAT_CRITERION, total_weight, weighted_total
from .evaluator import DeckEvaluator
from .extract import DeckExtractionError
from .schemas import DeckEvaluation

__all__ = [
    "CRITERIA",
    "FORMAT_CRITERION",
    "DeckEvaluation",
    "DeckEvaluator",
    "DeckExtractionError",
    "total_weight",
    "weighted_total",
]
