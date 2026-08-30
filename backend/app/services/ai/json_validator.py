"""
JSON Validator — json_validator.py

Validates parsed AI response data against Pydantic schemas.
This is the final gate before any AI-generated data enters business logic.

Design principle: If validation fails twice (initial + one retry), return a
controlled error — never crash the interview engine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class AIValidationError(Exception):
    """
    Raised when an AI response fails Pydantic schema validation.

    Carries the structured validation errors and the raw data for debugging.
    The interview engine catches this and returns a controlled degraded response.
    Never propagates to the user as an unhandled exception.
    """

    def __init__(
        self,
        schema_name: str,
        validation_errors: Sequence[Mapping[str, Any]],
        raw_data: Any,
    ) -> None:
        self.schema_name = schema_name
        self.validation_errors = validation_errors
        self.raw_data = raw_data
        super().__init__(
            f"AI response failed validation against schema '{schema_name}': "
            f"{len(validation_errors)} error(s). "
            f"First error: {validation_errors[0].get('msg', 'unknown') if validation_errors else 'none'}"
        )


class JSONValidator:
    """
    Validates a parsed dictionary against a Pydantic BaseModel schema.

    Only used by ResponseParser — do not call from services directly.
    Services should interact with ResponseParser.parse(), which handles
    both extraction and validation in one call.
    """

    def validate(self, data: dict[str, Any], schema: type[T]) -> T:
        """
        Validate data against schema.

        Returns:
            A fully validated schema instance.

        Raises:
            AIValidationError: If validation fails. Contains structured error
                               detail and the raw data for debugging.
        """
        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            errors = exc.errors(include_url=False)
            logger.error(
                "ai_response_validation_failed",
                schema=schema.__name__,
                error_count=len(errors),
                # `errors[0]` carries pydantic's `input` — the offending VALUE — so the
                # error is reduced to the parts that describe the problem rather than the
                # data. `loc` is the field path and `type` is the rule that failed, which is
                # everything needed to fix a prompt.
                first_error=(
                    {"loc": errors[0].get("loc"), "type": errors[0].get("type")}
                    if errors
                    else None
                ),
                # `raw_data_preview=str(data)[:300]` USED TO BE HERE. On a report schema that
                # is 300 characters of a candidate's assessment. The keys diagnose a shape
                # mismatch without carrying any of the values.
                keys=sorted(data)[:15] if isinstance(data, dict) else None,
            )
            raise AIValidationError(
                schema_name=schema.__name__,
                validation_errors=errors,
                raw_data=data,
            ) from exc
