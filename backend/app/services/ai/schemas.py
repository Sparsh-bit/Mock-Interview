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
    mentioned_concepts: list[str] = Field(default_factory=list)
    missed_concepts: list[str] = Field(default_factory=list)


class QuizQuestion(BaseModel):
    """A single MCQ from app/prompts/quiz_generator.md."""

    question: str
    options: list[str] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0)
    explanation: str = ""
    topic: str = "General"
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class QuizGeneration(BaseModel):
    """Full quiz output from app/prompts/quiz_generator.md."""

    questions: list[QuizQuestion] = Field(default_factory=list)


class GeneratedQuestion(BaseModel):
    """Matches the output of app/prompts/question_generator.md."""

    content: str
    topic_name: str = "General"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    question_type: Literal["conceptual", "practical", "scenario", "coding", "design"] = "conceptual"
    expected_keywords: list[str] = Field(default_factory=list)
    ideal_answer: str = ""


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


class ImprovementResourceItem(BaseModel):
    type: str
    title: str
    url: str | None = None
    author: str | None = None


class ImprovementRoadmapItem(BaseModel):
    priority: int
    topic: str
    current_score: float
    target_score: float
    study_hours_estimate: int
    resources: list[ImprovementResourceItem] = Field(default_factory=list)


class QuestionAnalysisItem(BaseModel):
    question_id: str
    question: str
    answer_quality: Literal["excellent", "good", "partial", "incorrect", "no_answer"]
    score: float = Field(ge=0.0, le=10.0)
    missing_concepts: list[str] = Field(default_factory=list)
    ideal_answer_summary: str = ""


class ReportGeneratorResponse(BaseModel):
    """Full response schema for the `report_generator` prompt template."""

    executive_summary: str
    readiness_level: Literal["interview_ready", "close_to_ready", "needs_more_practice", "significant_gaps"]
    readiness_reasoning: str
    overall_score: float = Field(ge=0.0, le=100.0)
    overall_score_label: str
    topic_scores: dict[str, float] = Field(default_factory=dict)
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    performance_percentile: int = Field(ge=0, le=100, default=50)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    question_analysis: list[QuestionAnalysisItem] = Field(default_factory=list)
    improvement_roadmap: list[ImprovementRoadmapItem] = Field(default_factory=list)
