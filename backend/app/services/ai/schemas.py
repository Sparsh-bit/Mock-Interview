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


class GDContribution(BaseModel):
    speaker: str
    text: str


class GDPanelTurn(BaseModel):
    """Matches the output of app/prompts/gd_panel.md."""

    contributions: list[GDContribution] = Field(default_factory=list)
    #: True when this turn puts a direct question or invitation to the real
    #: candidate. The client uses it to show that the candidate is on the spot
    #: and to start counting unanswered questions against them.
    addressed_candidate: bool = False


class PanelUtterance(BaseModel):
    """
    One line from one interviewer, with how it is delivered.

    Separate from GDContribution because of `tone`. A discussion panellist argues in one
    register throughout; an interviewer does not — putting a question and telling somebody
    their answer is wrong are different acts, and hearing them in the same voice is the
    clearest possible tell that nobody is really there. The model tags each line because
    the model is the only thing that knows which one is the correction; inferring it back
    out of the text with keywords would be guessing at what it already knew.
    """

    speaker: str
    text: str
    #: A name from TONE_PROSODY in services/tts/base.py. Free-form rather than an enum so
    #: an unexpected value degrades to neutral speech instead of failing validation and
    #: costing the whole turn — the panel falling silent is far worse than a flat line.
    tone: str = "neutral"


class InterviewPanelTurn(BaseModel):
    """Matches the output of app/prompts/interview_panel.md."""

    turns: list[PanelUtterance] = Field(default_factory=list)
    #: True when one of these turns actually puts the given question to the candidate.
    #: False for a stage that does not ask one — a wrap-up decline, the "any questions for
    #: us?" prompt, or answering something the candidate asked. The caller uses it to decide
    #: whether the question it supplied has now been spent.
    asked_question: bool = False


class GDPreparedTopic(BaseModel):
    """
    Matches the output of app/prompts/gd_topic_prep.md.

    What the AI produces when a candidate types their own GD topic. A raw phrase
    like "AI in education" is not a discussable motion — a real GD is given a
    proposition with two defensible sides, so this turns the phrase into one and
    supplies the framing a moderator would read out.
    """

    #: The topic restated as something you can actually argue about.
    statement: str
    #: One or two sentences of context, as a moderator would introduce it.
    framing: str = ""
    #: Points the "for" side would make. Shown to the candidate as preparation.
    points_for: list[str] = Field(default_factory=list)
    points_against: list[str] = Field(default_factory=list)
    #: False when the input is not a viable discussion topic at all.
    usable: bool = True
    #: Why it was rejected, when usable is False.
    reason: str = ""


class GDEvaluation(BaseModel):
    """Matches the output of app/prompts/gd_evaluator.md."""

    contribution_score: float = Field(ge=0.0, le=10.0)
    relevance_score: float = Field(ge=0.0, le=10.0)
    clarity_score: float = Field(ge=0.0, le=10.0)
    engagement_score: float = Field(ge=0.0, le=10.0)
    overall_score: float = Field(ge=0.0, le=10.0)
    feedback: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)


class CommunicationEvaluation(BaseModel):
    """Matches the output of app/prompts/communication_evaluator.md."""

    clarity_score: float = Field(ge=0.0, le=10.0)
    structure_score: float = Field(ge=0.0, le=10.0)
    confidence_score: float = Field(ge=0.0, le=10.0)
    conciseness_score: float = Field(ge=0.0, le=10.0)
    overall_score: float = Field(ge=0.0, le=10.0)
    pace_feedback: str = ""
    filler_feedback: str = ""
    feedback: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)


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


class InterviewPlan(BaseModel):
    """Matches the output of app/prompts/interview_plan.md."""

    topics: list[str] = Field(default_factory=list)
    questions: list[GeneratedQuestion] = Field(default_factory=list)


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


class CodeBug(BaseModel):
    """A single defect found in a coding submission."""

    description: str
    severity: Literal["critical", "major", "minor", "style"] = "minor"
    #: The model often cannot pin a line; treat it as a hint, not a guarantee.
    line: int | None = None
    fix: str = ""


class CodingEvaluation(BaseModel):
    """Matches the output of app/prompts/coding_evaluator.md."""

    #: Graded rather than binary — freshers are usually partly right, and
    #: "incorrect" is useless feedback.
    correctness_level: Literal["correct", "nearly_correct", "partially_correct", "incorrect"]
    summary: str
    #: Whether they reached for the obvious solution or something better. A
    #: working brute force is a legitimate interview pass.
    approach: Literal["brute_force", "optimised", "optimal", "wrong_approach"]
    is_brute_force_sound: bool = True

    time_complexity: str = ""
    optimal_time_complexity: str = ""
    space_complexity: str = ""
    optimal_space_complexity: str = ""

    correctness_score: float = Field(ge=0.0, le=10.0)
    efficiency_score: float = Field(ge=0.0, le=10.0)
    code_quality_score: float = Field(ge=0.0, le=10.0)
    overall_score: float = Field(ge=0.0, le=10.0)

    bugs: list[CodeBug] = Field(default_factory=list)
    edge_cases_missed: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    optimisation_hint: str = ""
    follow_up_questions: list[str] = Field(default_factory=list)

    # Soft, explicitly-fallible signal that the submission may not be the
    # candidate's own work. Never presented as fact — see the prompt's rules.
    ai_authorship_suspected: bool = False
    ai_authorship_confidence: Literal["low", "medium", "high"] = "low"
    ai_authorship_signals: list[str] = Field(default_factory=list)
    ai_authorship_note: str = ""


# ─── Resume analysis ──────────────────────────────────────────────────────────


class ResumeSkill(BaseModel):
    """One skill claimed on the resume, with how strongly it was claimed."""

    name: str
    domain: str = ""
    years_experience: float | None = None
    #: How the claim was made. "explicit" is a stated proficiency, "inferred" is
    #: deduced from a project, "mentioned_once" is a passing reference — the
    #: interviewer treats these very differently when deciding how hard to probe.
    confidence: Literal["explicit", "inferred", "mentioned_once"] = "inferred"
    proficiency_level: Literal["beginner", "intermediate", "advanced", "expert"] = "intermediate"


class ResumeProject(BaseModel):
    """A project described on the resume — the richest source of real questions."""

    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    role: str = ""
    scale_indicators: list[str] = Field(default_factory=list)
    relevance_to_track: Literal["high", "medium", "low"] = "medium"


class ResumeExperience(BaseModel):
    """Overall shape of the candidate's experience."""

    total_years: float = 0.0
    seniority_level: Literal["junior", "mid", "senior", "principal"] = "junior"
    primary_stack: list[str] = Field(default_factory=list)
    domain: str = ""


class ResumeInterviewFocus(BaseModel):
    """
    How the interview should be steered for this candidate.

    This is the part that actually changes the interview: priority_topics drives
    question selection and personalization_notes is handed to the interviewer so
    it can say "as you mentioned in your resume…" about something real.
    """

    strong_areas: list[str] = Field(default_factory=list)
    weak_areas: list[str] = Field(default_factory=list)
    priority_topics: list[str] = Field(default_factory=list)
    recommended_difficulty: Literal["easy", "medium", "hard"] = "medium"
    personalization_notes: str = ""


class ResumeQuality(BaseModel):
    """Feedback on the resume itself, shown to the candidate."""

    completeness_score: float = Field(ge=0.0, le=10.0, default=5.0)
    technical_depth_score: float = Field(ge=0.0, le=10.0, default=5.0)
    concerns: list[str] = Field(default_factory=list)


class ResumeAnalysisResponse(BaseModel):
    """Matches the output of app/prompts/resume_analyzer.md."""

    skills: list[ResumeSkill] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    experience: ResumeExperience = Field(default_factory=ResumeExperience)
    interview_focus: ResumeInterviewFocus = Field(default_factory=ResumeInterviewFocus)
    resume_quality: ResumeQuality = Field(default_factory=ResumeQuality)


# ─── Model answer coaching ────────────────────────────────────────────────────


class ModelAnswerResponse(BaseModel):
    """
    Matches the output of app/prompts/model_answer.md.

    Deliberately NOT part of the report schema. Generating a full spoken model
    answer for every question would roughly double the report's output tokens (the
    single most expensive call in the app) for content most candidates read for
    only a few questions. This is produced on demand per answer and cached.
    """

    #: The answer as the candidate should have spoken it. Length is set by the
    #: question — a definition gets ~50 words, a design question ~250 — because a
    #: padded answer to a simple question reads as waffle to a real interviewer.
    model_answer: str
    what_was_missing: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    verdict_line: str = ""
