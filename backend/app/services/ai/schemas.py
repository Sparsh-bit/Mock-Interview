"""
AI Response Schemas — services/ai/schemas.py

Pydantic schemas the AI provider's JSON output must satisfy, validated via
ResponseParser/JSONValidator before any AI-generated data touches business
logic. Field shapes mirror the documented `## Output Format` block in the
corresponding prompt template under app/prompts/ — keep them in sync.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnswerEvaluation(BaseModel):
    """Matches the `evaluation` object in app/prompts/interviewer.md."""

    technical_score: float = Field(ge=0.0, le=10.0)
    communication_score: float = Field(ge=0.0, le=10.0)
    completeness_score: float = Field(ge=0.0, le=10.0)
    confidence_score: float = Field(ge=0.0, le=10.0)
    overall_score: float = Field(ge=0.0, le=10.0)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    feedback: str
    is_bluffing_detected: bool = False
    follow_up_recommended: bool = False
    follow_up_reason: (
        Literal["incomplete_answer", "bluffing_detected", "strong_answer_deepen", "clarification_needed"]
        | None
    ) = None


class InterviewState(BaseModel):
    """Matches the `interview_state` object in app/prompts/interviewer.md."""

    topic_coverage_percent: int = Field(ge=0, le=100, default=0)
    suggested_difficulty_adjustment: Literal["increase", "decrease", "maintain"] = "maintain"
    session_notes: str = ""


class InterviewerResponse(BaseModel):
    """Full response schema for the `interviewer` prompt template."""

    next_question: str = ""
    evaluation: AnswerEvaluation
    interview_state: InterviewState = Field(default_factory=InterviewState)
