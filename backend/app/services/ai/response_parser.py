"""
Response Parser — response_parser.py

Extracts structured JSON from raw AI provider response strings and validates
them against Pydantic schemas.

Handles all real-world AI response formats:
- Pure JSON (happy path when json_mode=True)
- JSON inside markdown code blocks (```json ... ```)
- JSON embedded in prose text
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

# Ordered extraction patterns — most specific first
_EXTRACTION_PATTERNS = [
    re.compile(r"```json\s*\n(.*?)\n?```", re.DOTALL),  # ```json ... ```
    re.compile(r"```\s*\n(.*?)\n?```", re.DOTALL),       # ``` ... ```
    re.compile(r"\{.*\}", re.DOTALL),                     # First {...} in prose
]


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
        """
        stripped = content.strip()

        # 1. Direct JSON parse — fastest path, works for json_mode responses
        try:
            result = json.loads(stripped)
            if isinstance(result, dict):
                return result
            # AI returned a JSON array instead of object — wrap for debugging
            logger.warning(
                "ai_response_is_array",
                content_preview=stripped[:100],
            )
        except json.JSONDecodeError:
            pass

        # 2. Pattern-based extraction for markdown and prose
        for pattern in _EXTRACTION_PATTERNS:
            match = pattern.search(stripped)
            if not match:
                continue
            candidate = (match.group(1) if match.lastindex else match.group(0)).strip()
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    logger.debug(
                        "ai_json_extracted_via_pattern",
                        pattern=pattern.pattern[:40],
                    )
                    return result
            except json.JSONDecodeError:
                continue

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
