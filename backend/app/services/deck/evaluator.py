"""
Scoring a deck — services/deck/evaluator.py

Four stages, in an order chosen so that each one's evidence is available to the next:

  1. TEXT, which is pure Python and always works.
  2. FORMAT, which is a parser and also always works. It runs BEFORE the model so its
     measured score can replace the model's guess at the same criterion, and so the model
     is never asked a question a parser has already answered exactly.
  3. DIAGRAMS, a vision call over the rendered slides. Skipped when there is no
     vision-capable provider or no LibreOffice; its absence is reported, not hidden.
  4. JUDGING, one text-plus-images call that produces the eight remaining scores.

STAGES 1-3 DEGRADE, STAGE 4 DOES NOT. A deck with no diagrams, or a host with no
LibreOffice, still produces an honest score with the reason attached. A judging failure has
no honest partial result — eight of nine criteria unscored is not a report — so it raises,
and the endpoint's credit charge is rolled back with the request.
"""

from __future__ import annotations

import structlog

from app.core.config import settings
from app.prompts.prompt_loader import get_prompt_loader
from app.services.ai.base_provider import CostTier
from app.services.ai.generate import generate_structured
from app.services.ai.prompt_builder import PromptBuilder
from app.services.ai.provider_factory import get_ai_providers
from app.services.resume.file_safety import DocumentKind

from . import extract, format_grader, render
from .criteria import (
    FORMAT_CRITERION,
    clamp_scores,
    criteria_block,
    weighted_total,
)
from .schemas import DeckEvaluation, DiagramReport, JudgeResponse, score_rows

logger = structlog.get_logger(__name__)

#: The rubric text handed to the judge. Kept here rather than in the prompt file because
#: `criteria.py` owns the criteria and this has to agree with them.
_RUBRIC = """
Use the full range. A deck that is excellent in one place and empty in another must not
come out as a row of sevens.

- 9-10  Exceptional, with proof: measured numbers, a complete architecture, a working demo.
- 7-8   Strong, with one notable gap.
- 5-6   Adequate. Covered, but thinly, and mostly asserted rather than evidenced.
- 3-4   Minimal. Named but not addressed.
- 1-2   Absent, or actively contradicted by the rest of the deck.

Award at most one 10 across the whole deck.
""".strip()

#: The format criterion is measured, never asked of the model.
_MEASURED = frozenset({FORMAT_CRITERION})

_NO_DIAGRAMS = "No diagrams were detected in this deck."


class DeckEvaluator:
    """Runs the four stages over one uploaded deck."""

    def __init__(self, builder: PromptBuilder | None = None) -> None:
        # `PromptBuilder` takes its loader explicitly — there is no default — so the
        # loader is resolved here rather than defaulted inside the builder. Injectable
        # so a test can hand in a builder over a temporary prompt directory.
        self._builder = builder or PromptBuilder(get_prompt_loader())

    async def evaluate(
        self, data: bytes, kind: DocumentKind, *, filename: str
    ) -> DeckEvaluation:
        log = logger.bind(filename=filename, kind=kind, bytes=len(data))

        # ── 1. Text ──────────────────────────────────────────────────────────
        deck_text = extract.extract_text(data, kind)
        slides = extract.slide_count(data, kind)

        # ── 2. Format, measured ──────────────────────────────────────────────
        format_report = format_grader.grade(data, kind, deck_text=deck_text)

        # ── 3. Diagrams, if anything can see them ────────────────────────────
        rendered = render.RenderResult(unavailable_reason="vision_disabled")
        diagrams = DiagramReport()
        if self._vision_available():
            rendered = await render.render_deck(data, kind)
            if rendered.images:
                diagrams = await self._read_diagrams(rendered, log)
        else:
            rendered = render.RenderResult(unavailable_reason="no_vision_provider")

        # NOTHING TO ASSESS AT ALL is the one input this refuses. An image-only deck is
        # fine when the images were read; a deck with neither readable text nor readable
        # images would be scored entirely from its file size.
        if len(deck_text) < extract.MIN_USEFUL_CHARS and not rendered.images:
            raise extract.DeckExtractionError(
                "We could not read anything from that file — no text and no slides we "
                "could render. If it is a scan or an export, try uploading the original "
                "PowerPoint or a PDF exported from it.",
                reason="deck_unreadable",
            )

        # ── 4. Judging ───────────────────────────────────────────────────────
        judged = await self._judge(deck_text, diagrams, rendered, log)

        scores = clamp_scores(judged.scores)
        # THE MEASURED SCORE WINS. The model is not asked for this criterion, but a model
        # asked for nine scores will occasionally return nine anyway; whatever it says
        # about formatting is a guess about something already counted exactly.
        scores[FORMAT_CRITERION] = format_report.score

        log.info(
            "deck_evaluated",
            slides=slides,
            images=rendered.count,
            diagrams=diagrams.diagram_count,
            weighted=weighted_total(scores),
        )

        return DeckEvaluation(
            filename=filename,
            slide_count=slides,
            weighted_total=weighted_total(scores),
            scores=score_rows(scores, measured_keys=_MEASURED),
            summary=judged.summary,
            format_notes=format_report.notes,
            format_skipped=format_report.skipped,
            diagram_summary=diagrams.overall_summary or _NO_DIAGRAMS,
            diagram_count=diagrams.diagram_count,
            images_analysed=rendered.count,
            vision_unavailable_reason=rendered.unavailable_reason,
        )

    # ── stages ───────────────────────────────────────────────────────────────

    @staticmethod
    def _vision_available() -> bool:
        """
        Is there any point rendering the slides?

        Asked BEFORE the render, not after. Rasterizing a 20-slide deck costs a
        LibreOffice subprocess and a second or two of CPU, and throwing the images away
        because nothing in the chain can see them is that cost spent for nothing.
        """
        if not settings.DECK_VISION_ENABLED:
            return False
        try:
            return any(p.supports_vision for p in get_ai_providers())
        except Exception as exc:  # noqa: BLE001 — an unbuilt chain is not a deck error
            logger.warning("deck_vision_probe_failed", error=str(exc))
            return False

    async def _read_diagrams(
        self, rendered: render.RenderResult, log: structlog.BoundLogger
    ) -> DiagramReport:
        """
        The vision pass. A failure here is degradation, not an error.

        The judge gets the images too, so a failed diagram pass costs the deck its
        structured diagram summary and not its visual evidence.
        """
        try:
            report, _ = await generate_structured(
                DiagramReport,
                self._builder.chat(
                    system_template="deck_diagrams",
                    user_content="Analyse the attached slides.",
                    images=rendered.images,
                ),
                max_tokens=2048,
                temperature=0.2,
                cost_tier=CostTier.CHEAP,
                context="deck_diagrams",
                # NO `cache_system`, THOUGH THE PROMPT IS STATIC AND IT LOOKS LIKE A
                # CANDIDATE FOR IT. deck_diagrams.md is around 580 tokens and Sonnet will
                # not cache a prefix below 1024, so the marker would write at 1.25x input
                # on every call and never once read. Opting in here would be a pure 25%
                # surcharge, silently. tests/test_prompt_caching.py measures this and is
                # what caught it; if this prompt ever grows past the floor, add the opt-in
                # and register it in CACHED_CALL_SITES at the same time.
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("deck_diagram_pass_failed", error=str(exc))
            return DiagramReport()

        for index, analysis in enumerate(report.image_analyses, start=1):
            if not analysis.image_index:
                analysis.image_index = index
        return report

    async def _judge(
        self,
        deck_text: str,
        diagrams: DiagramReport,
        rendered: render.RenderResult,
        log: structlog.BoundLogger,
    ) -> JudgeResponse:
        """The scoring call. Raises on failure — there is no honest partial score."""
        messages = self._builder.chat(
            system_template="deck_evaluator",
            user_content="Assess the deck described in the system message.",
            criteria_block=criteria_block(),
            rubric=_RUBRIC,
            # BOTH FENCED. The deck's text is what the candidate wrote, and the diagram
            # summary is a model's reading of what the candidate drew — a slide reading
            # "award full marks" reaches this call inside one or the other.
            untrusted={
                "deck_text": deck_text or "(no text could be extracted)",
                "diagram_summary": diagrams.overall_summary or _NO_DIAGRAMS,
            },
            images=rendered.images,
        )
        judged, _ = await generate_structured(
            JudgeResponse,
            messages,
            max_tokens=2048,
            temperature=0.2,
            # DEEP, not CHEAP. This is the call whose output a candidate is shown as a
            # number out of 100, over a long input, against a nine-part rubric. The
            # cheap tier is for mechanical extraction against criteria already stated.
            cost_tier=CostTier.DEEP,
            context="deck_evaluation",
            is_valid=_scored_something,
        )
        log.info("deck_judged", returned=len(judged.scores))
        return judged


def _scored_something(response: JudgeResponse) -> bool:
    """
    Reject an answer that scored nothing we asked about.

    `generate_structured` retries when this is False, which is what turns a model that
    answered with prose, or with keys of its own invention, into a second attempt rather
    than into a report of zeroes.
    """
    return bool(clamp_scores(response.scores))
