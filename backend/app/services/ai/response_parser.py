"""
Response Parser — response_parser.py

Extracts structured JSON from raw AI provider response strings and validates
them against Pydantic schemas.

Handles all real-world AI response formats:
- Pure JSON (happy path when json_mode=True)
- JSON inside markdown code blocks (```json ... ```)
- JSON embedded in prose text
- JSON cut off mid-flight because the call hit its max_tokens ceiling
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel

from .json_validator import AIValidationError, JSONValidator

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_CLOSERS = {"{": "}", "[": "]"}

# Ordered extraction patterns — most specific first
_EXTRACTION_PATTERNS = [
    re.compile(r"```json\s*\n(.*?)\n?```", re.DOTALL),  # ```json ... ```
    re.compile(r"```\s*\n(.*?)\n?```", re.DOTALL),       # ``` ... ```
    re.compile(r"\{.*\}", re.DOTALL),                     # First {...} in prose
]


def _repair_truncated_json(content: str) -> str | None:
    """
    Close a JSON object that the model was cut off in the middle of writing.

    WHY THIS IS WORTH DOING AT ALL. A response that hits its `max_tokens` ceiling is
    not garbage — it is a correct answer with the end missing. Resume analysis was
    losing 27 extracted skills because the `projects` array after them was clipped
    mid-object: the body would not parse, so the whole billed call was discarded and
    retried, and the retry hit the same ceiling in the same place. Three measured
    runs, twelve billed calls, every one `finish_reason=length`, and the candidate
    got an upload with no skills and no projects. The ceilings that caused that are
    fixed at the call sites, but a ceiling is a ceiling: any of them can be reached
    by an unusually verbose answer, and every feature in the app is one truncation
    away from throwing away work it has already paid for.

    HOW. Walk the text tracking string/escape state and the stack of open brackets,
    remembering the last position at which the structure was at a clean boundary —
    after a comma, or after a nested container closed. Truncate back to that
    boundary and close whatever is still open. The result is the complete prefix of
    the model's answer and nothing invented: partial objects at the cut are dropped
    rather than guessed at.

    Returns None when there is nothing to salvage, or when the text is not truncated
    at all (an unbalanced-but-not-truncated body is a different failure and must
    still be reported as one). The caller only reaches here after normal parsing has
    already failed, and every result still goes through Pydantic validation and the
    call site's `is_valid` predicate afterwards — so a salvaged fragment that is
    schema-valid but useless is still rejected and retried.
    """
    start = content.find("{")
    if start < 0:
        return None

    stack: list[str] = []
    in_string = False
    escaped = False
    #: (cut index, open brackets at that point). The stack has to be captured, not
    #: just its depth: by the time we truncate, a container that was open at the
    #: boundary may have closed and a different one opened at the same depth, and
    #: closing with today's stack would emit the wrong bracket.
    safe: tuple[int, tuple[str, ...]] | None = None

    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in _CLOSERS:
            stack.append(char)
        elif char in ("}", "]"):
            if not stack or _CLOSERS[stack[-1]] != char:
                return None  # not truncated — genuinely malformed
            stack.pop()
            if stack:
                safe = (index + 1, tuple(stack))
        elif char == "," and stack:
            safe = (index, tuple(stack))

    if not stack:
        return None  # balanced: whatever is wrong with it, truncation is not it
    if safe is None:
        return None  # cut before a single complete element — nothing to keep

    cut, open_brackets = safe
    body = content[start:cut].rstrip().rstrip(",")
    closers = "".join(_CLOSERS[bracket] for bracket in reversed(open_brackets))
    return body + closers


class ResponseParser:
    """
    Extracts and validates structured JSON from AI provider response strings.

    The retry logic lives here, not in the provider:
    - On AIValidationError: try up to 1 additional time by re-calling the provider.
    - If it fails again: re-raise for the service to handle as a controlled error.

    Usage in services (via DI):
        class EvaluationService:
            def __init__(self, provider: BaseAIProvider, parser: ResponseParser):
                ...
            async def evaluate(self, answer: str) -> AnswerEvaluationSchema:
                request = ProviderRequest(messages=..., json_mode=True)
                response = await self._provider.complete(request)
                return self._parser.parse(response.content, AnswerEvaluationSchema)
    """

    def __init__(self, validator: JSONValidator) -> None:
        self._validator = validator

    def parse(self, content: str, schema: type[T]) -> T:
        """
        Extract JSON from content and validate against schema.

        Args:
            content: Raw string from AI provider response.
            schema: Pydantic model class to validate against.

        Returns:
            Validated schema instance.

        Raises:
            AIValidationError: If JSON cannot be extracted or validation fails.
        """
        raw = self._extract_json(content)
        return self._validator.validate(raw, schema)

    def _extract_json(self, content: str) -> dict[str, Any]:
        """
        Extract the first valid JSON object from content.

        Tries direct parse first (fastest), then pattern-based extraction.

        EVERY PARSE HERE IS `strict=False`, AND THAT IS A BUG FIX, NOT A RELAXATION.

        Reported as the ideal answer never generating on the detailed-analysis page. The model
        was not failing and was not running out of tokens — the logged call completed with
        `stop_reason=end_turn` at 893 of 1400 tokens and then failed validation. The reason was
        a single character: a literal newline inside a JSON string value, which strict JSON
        forbids. `json.loads` raised "Invalid control character at line 2 column 334", every
        extraction pattern hit the same error, and the response was reported as containing no
        JSON at all.

        This is ordinary model behaviour rather than an anomaly, and it scales with prose
        length: the longer the string being written, the likelier one raw newline lands in it.
        That is exactly why the symptom looked arbitrary — short conceptual answers came back
        fine and long design answers failed, so it read as "sometimes broken".

        `strict=False` permits control characters inside strings and changes nothing else: the
        grammar, the types, and the schema validation that runs afterwards are all untouched.
        A control character in a string is a quoting slip in content we are about to hand to
        Pydantic anyway, not a structural ambiguity — there is no second reading of the
        document to be wrong about.

        Applied to ALL THREE attempts deliberately. Fixing only the fast path would leave the
        pattern-based and truncation-salvage routes throwing on the same character, so the same
        response would still fail whenever it arrived wrapped in a fence.
        """
        stripped = content.strip()

        # 1. Direct JSON parse — fastest path, works for json_mode responses
        try:
            result = json.loads(stripped, strict=False)
            if isinstance(result, dict):
                return result
            # AI returned a JSON array instead of object — wrap for debugging
            logger.warning(
                "ai_response_is_array",
                content_preview=stripped[:100],
            )
        except json.JSONDecodeError:
            pass

        # 2. Pattern-based extraction for markdown and prose.
        #
        #    ALL MATCHES, MERGED — not the first one. A model writing a long response
        #    sometimes SPLITS ONE OBJECT ACROSS SEVERAL FENCED BLOCKS, and taking the first
        #    silently discarded the rest.
        #
        #    Reported as the ideal answer's "detailed analysis" never appearing. For a design
        #    question the model reliably emitted two blocks: `{"model_answer": ...}` and then
        #    a second `{"what_was_missing": [...], "key_points": [...], "verdict_line": ...}`.
        #    The first parsed cleanly, so nothing errored and nothing was logged — the request
        #    succeeded with the three coaching fields at their empty defaults, which is the
        #    only part of that response a candidate actually needed. Short conceptual answers
        #    fit in one block and were fine, so the failure looked arbitrary.
        #
        #    Merging is the right reading rather than a guess: the contract is ONE object, so
        #    several top-level objects in one response are fragments of it, never rival
        #    answers. Earlier fragments win a key collision, which keeps the old
        #    first-match-wins behaviour for anything that was already working.
        for pattern in _EXTRACTION_PATTERNS:
            fragments: list[dict[str, Any]] = []
            for match in pattern.finditer(stripped):
                candidate = (match.group(1) if match.lastindex else match.group(0)).strip()
                try:
                    parsed = json.loads(candidate, strict=False)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    fragments.append(parsed)
            if not fragments:
                continue
            merged: dict[str, Any] = {}
            for fragment in fragments:
                for key, value in fragment.items():
                    merged.setdefault(key, value)
            if len(fragments) > 1:
                # Never silent. One object arriving as several blocks is worth seeing in the
                # logs — it is a prompt that invites the split, and the next field added to
                # that schema may land in a fragment nothing thought to merge.
                logger.warning(
                    "ai_json_merged_from_fragments",
                    fragments=len(fragments),
                    keys=sorted(merged)[:12],
                )
            else:
                logger.debug(
                    "ai_json_extracted_via_pattern",
                    pattern=pattern.pattern[:40],
                )
            return merged

        # 3. Truncation salvage — the model ran out of tokens mid-answer. Last
        #    resort, and never silent: a truncated response means a call site's
        #    max_tokens is too low for what its prompt asks for, which is a bug to
        #    fix rather than a condition to absorb quietly.
        repaired = _repair_truncated_json(stripped)
        if repaired is not None:
            try:
                result = json.loads(repaired, strict=False)
            except json.JSONDecodeError:
                result = None
            if isinstance(result, dict):
                logger.warning(
                    "ai_json_salvaged_from_truncation",
                    kept_chars=len(repaired),
                    original_chars=len(stripped),
                    keys=sorted(result)[:12],
                )
                return result

        logger.error(
            "ai_json_extraction_failed",
            content_preview=content[:400],
        )
        raise AIValidationError(
            schema_name="<json_extraction>",
            validation_errors=[
                {"msg": "No valid JSON object found in AI response", "type": "json_error"}
            ],
            raw_data=content,
        )
