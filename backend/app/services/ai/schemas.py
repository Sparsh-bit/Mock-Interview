"""
AI Response Schemas — services/ai/schemas.py

Pydantic schemas the AI provider's JSON output must satisfy, validated via
ResponseParser/JSONValidator before any AI-generated data touches business
logic. Field shapes mirror the documented `## Output Format` block in the
corresponding prompt template under app/prompts/ — keep them in sync.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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


class QuestionBatch(BaseModel):
    """
    Several questions generated at once for the shared, cached pool.

    Reuses GeneratedQuestion so the batch and the single-question path cannot drift into
    different shapes — the batch is the same thing, five times, generated without any
    candidate context so it can be shared. See orchestrator._bank_question.
    """

    questions: list[GeneratedQuestion] = Field(default_factory=list)


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


class StudyResource(BaseModel):
    """One study resource for a topic. Mirrors ImprovementResourceItem, generated shape."""

    type: str = "reference"
    title: str
    #: Optional because the prompt tells the model to omit a URL it is not certain of,
    #: rather than invent one. A titled resource with no link is still findable; a
    #: confident dead link is worse than nothing.
    url: str | None = None
    author: str | None = None


class StudyResourceList(BaseModel):
    """
    Output of the shared, topic-keyed resource generation.

    Cached globally by topic — see services/prep/study_resources.py. Nothing about a
    candidate reaches this prompt, which is what makes it safe to share.
    """

    resources: list[StudyResource] = Field(default_factory=list)


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


class ReportSummaryResponse(BaseModel):
    """
    The whole-interview half of a report — everything except the per-question breakdown.

    Matches app/prompts/report_summary.md. Deliberately has NO `question_analysis` field:
    that half is generated concurrently in batches, and a field here would let the model
    spend the response on it. See report_analysis.md for why the report is split at all.
    """

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
    improvement_roadmap: list[ImprovementRoadmapItem] = Field(default_factory=list)


class ReportAnalysisResponse(BaseModel):
    """
    One batch of per-question analyses. Matches app/prompts/report_analysis.md.

    A batch covers a SLICE of the interview, so a batch that fails costs its own questions
    and nothing else — which is the whole point of generating them separately.
    """

    question_analysis: list[QuestionAnalysisItem] = Field(default_factory=list)


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


class _NullMeansUnset(BaseModel):
    """
    Treat an explicit `null` from the model as "this field was not stated".

    MEASURED, on the very first run after the analysis was split. The projects half
    came back complete and well inside its token ceiling
    (`finish_reason=end_turn`, 1063 of 2000 tokens) and was thrown away anyway:

        ai_response_validation_failed
        loc=('projects', 0, 'role')  msg='Input should be a valid string'  input=None

    The resume did not say what the candidate's role on that project was, so the
    model wrote `"role": null` — which is the most natural possible thing for it to
    write, and exactly what our own prompt means by an omitted field. Pydantic
    rejects None for a `str` field, so four nulls in one otherwise perfect response
    invalidated the whole billed call. It cost that run 10 seconds and a retry
    (18.9s against 8.6s for the runs that did not hit it), and had the retry drawn
    another null the projects half would have been lost outright — arriving as the
    reported "projects are not been able to fetch" with nothing in the logs but a
    validation warning.

    Dropping the key rather than coercing it lets the field's own default apply, so
    there is one definition of "unset" instead of two. Fields already declared
    `X | None = None` are unaffected: their default is None either way.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data


class ResumeSkill(_NullMeansUnset):
    """
    One skill claimed on the resume, with how strongly it was claimed.

    `name` and `confidence` are the only fields the analyser prompt still ASKS
    for. The three below it are kept because old stored analyses contain them and
    must keep validating, but nothing in the application reads them — grep
    `proficiency_level` and the only hits are this file and a prompt that no
    longer exists. They were ~25 of the ~40 output tokens each skill cost, on the
    call whose output overran its token ceiling on every single attempt and left
    candidates with no skills at all. Requesting a field nothing reads is not free:
    it is paid for in the candidate's waiting time.

    So: do not add them back to resume_analyzer_skills.md. If one is ever genuinely
    needed, add the reader first.
    """

    name: str
    domain: str = ""
    years_experience: float | None = None
    #: How the claim was made. "explicit" is a stated proficiency, "inferred" is
    #: deduced from a project, "mentioned_once" is a passing reference — the
    #: interviewer treats these very differently when deciding how hard to probe.
    confidence: Literal["explicit", "inferred", "mentioned_once"] = "inferred"
    proficiency_level: Literal["beginner", "intermediate", "advanced", "expert"] = "intermediate"


class ResumeProject(_NullMeansUnset):
    """A project described on the resume — the richest source of real questions."""

    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    role: str = ""
    scale_indicators: list[str] = Field(default_factory=list)
    #: Not requested from the model any more, and not read anywhere — see the note
    #: on ResumeSkill. Retained so analyses stored before that change still validate.
    relevance_to_track: Literal["high", "medium", "low"] = "medium"


class ResumeExperience(_NullMeansUnset):
    """Overall shape of the candidate's experience."""

    total_years: float = 0.0
    seniority_level: Literal["junior", "mid", "senior", "principal"] = "junior"
    primary_stack: list[str] = Field(default_factory=list)
    domain: str = ""


class ResumeInterviewFocus(_NullMeansUnset):
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


class ResumeQuality(_NullMeansUnset):
    """
    Feedback on the resume itself.

    NOT REQUESTED AND NOT STORED. There is no column for it on ResumeFile, so it
    was generated, billed and dropped on the floor — about 120 output tokens per
    upload of prose nobody has ever seen, on the one call that could not afford
    them. It stays in the schema so a stored analysis that has it still validates.
    Wiring it up means adding a column and a reader first, then asking for it.
    """

    completeness_score: float = Field(ge=0.0, le=10.0, default=5.0)
    technical_depth_score: float = Field(ge=0.0, le=10.0, default=5.0)
    concerns: list[str] = Field(default_factory=list)


class ResumeSkillsHalf(_NullMeansUnset):
    """
    What app/prompts/resume_analyzer_skills.md returns.

    The analysis is requested as two concurrent halves rather than one object —
    see services/resume/analyser.py for the measurements that forced that. Each
    half gets its OWN model on purpose: every field of ResumeAnalysisResponse has
    a default, so a half validated against the combined model would happily accept
    the other half's answer (or an empty object) as a success. Validating the
    narrow shape means a misdirected response comes back with an empty `skills`
    list, which the call site's `is_valid` then rejects and retries.
    """

    skills: list[ResumeSkill] = Field(default_factory=list)
    experience: ResumeExperience = Field(default_factory=ResumeExperience)


class ResumeProjectsHalf(_NullMeansUnset):
    """What app/prompts/resume_analyzer_projects.md returns. See ResumeSkillsHalf."""

    projects: list[ResumeProject] = Field(default_factory=list)
    interview_focus: ResumeInterviewFocus = Field(default_factory=ResumeInterviewFocus)


class ResumeAnalysisResponse(_NullMeansUnset):
    """
    The merged resume analysis: ResumeSkillsHalf + ResumeProjectsHalf.

    EVERY FIELD HAS A DEFAULT, which is load-bearing in one direction and a trap in
    the other. It is what lets a half-successful analysis still be stored and used
    (one provider failure must not cost a candidate the half that worked, and
    api/v1/interview.py rebuilds this from stored columns that were never complete).
    It also means this model can NEVER reject an AI response — `{}` validates —
    so it must not be used as the schema of a live AI call without an `is_valid`
    predicate. It was, for one call, and that is precisely why uploads reported
    "Read and analysed" with zero skills and zero projects.
    """

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


class OpenDomainTopic(BaseModel):
    """One weighted area of an open-domain interview. Mirrors `domains.DomainProfile.topics`."""

    name: str = Field(min_length=2, max_length=48)
    weight: int = Field(ge=1, le=60)
    #: Is this the round about the candidate rather than about the subject — ownership,
    #: working with people, handling pressure and mistakes?
    #:
    #: A FLAG AND NOT A NAME MATCH, and that is the whole reason it exists. The curated
    #: profiles in `domains.py` all name this area "Behavioural & Ownership", so the pivot
    #: filter there can find it with a substring test. A generated profile names it in the
    #: field's own register — "Ownership & Collaboration", "Teamwork & Handover Discipline",
    #: "Bedside Manner & Escalation" — and a substring list over free-form names is the exact
    #: brittleness `domains._KEYWORDS` already demonstrates. So the model declares it.
    #:
    #: It matters because the pivot reads it: a candidate who has just admitted a gap is
    #: looking for ground in the SUBJECT, and "shall we talk about teamwork instead?" reads as
    #: giving up on the round rather than adapting it.
    behavioural: bool = False


class OpenDomainProfile(BaseModel):
    """
    A field of study or work the curated catalogue does not name, characterised as an
    interview domain. Matches the output of app/prompts/open_domain_profile.md.

    WHY THIS IS A SCHEMA AND NOT A FREE-TEXT BLOCK. The open-domain path exists because
    `domains._KEYWORDS` is a finite list and a candidate can type anything — a sommelier, a
    Bharatanatyam choreographer, a RISC-V firmware engineer. What it must NOT be is a second,
    looser way of describing an interview: the panel designations, the topic weighting, the
    self-rating subject and the technical flag are consumed by exactly the same code that
    consumes `domains.PROFILES`, so this has to arrive in exactly that shape or the two paths
    would diverge in the way `context.py`'s docstring describes as the worst bug this app has
    had.

    Being free-form is the reason for MORE validation here, not less. Every rule below has a
    counterpart in a file that already enforces it against hand-authored data:

      · weights summing to 100      `domains._validate` raises at import on the same thing.
      · no question text            `syllabus.py`'s anti-hardcode contract. A topic NAME is a
                                    subject; the moment it is a sentence addressed to the
                                    candidate, generated question text has been smuggled into
                                    the brief that is supposed to decide what gets generated.
      · a bounded number of areas   Two areas is not an interview and twelve is a syllabus
                                    nobody can allocate twelve questions across.
    """

    #: The field, named the way somebody in it would name it. "Sommelier & Wine Service".
    label: str = Field(min_length=2, max_length=60)
    #: Panel designations, lead first. Parallel to `domains.DomainProfile`.
    lead_role: str = Field(min_length=2, max_length=60)
    specialist_role: str = Field(min_length=2, max_length=60)
    #: Is this role asked engineering/scientific/technical content at all? Decides the code
    #: editor, the coding questions and the code-review stage.
    is_technical: bool
    #: What to ask the candidate to rate themselves on, as a noun phrase that reads naturally
    #: in "how would you rate yourself in ___". Decided by the model here for the same reason
    #: `_rating_subject` decides it from the profile elsewhere: the alternative is the model
    #: guessing mid-interview, and asked to guess it guesses Java.
    rating_subject: str = Field(min_length=2, max_length=60)
    topics: list[OpenDomainTopic] = Field(min_length=4, max_length=8)

    @model_validator(mode="after")
    def _no_question_text(self) -> OpenDomainProfile:
        """
        Reject a profile whose topic names are questions rather than subjects.

        The same rule `syllabus._validate` applies to hand-authored descriptors, applied here
        to model output for the same reason: this block is the INPUT that decides what
        questions get written, and a question in it is output fed back into input.
        """
        for topic in self.topics:
            name = topic.name.strip()
            if "?" in name:
                raise ValueError(f"topic name is a question, not a subject: {name!r}")
            first = name.lower().split(" ", 1)[0].strip("*_`")
            if first in _INTERROGATIVES:
                raise ValueError(f"topic name opens as a question: {name!r}")
        names = [t.name.strip().lower() for t in self.topics]
        if len(set(names)) != len(names):
            raise ValueError("topic names repeat — the weighting would double-count an area")
        return self

    @model_validator(mode="after")
    def _exactly_one_behavioural_area(self) -> OpenDomainProfile:
        """
        Every real interview has this round, and only one of them.

        Zero means the pivot cannot tell a subject area from a personal one and the plan has
        no behavioural row where every curated profile has one. Two or more means a third of
        the interview is about the candidate rather than the field, which is a different
        interview from the one they asked for.
        """
        flagged = [t for t in self.topics if t.behavioural]
        if len(flagged) != 1:
            raise ValueError(
                f"{len(flagged)} areas are marked behavioural, expected exactly one"
            )
        return self

    @model_validator(mode="after")
    def _weights_are_a_distribution(self) -> OpenDomainProfile:
        """
        Normalise the weights to sum to exactly 100 — or reject them outright.

        NORMALISING IS NOT THE SAME AS WAIVING THE RULE, and the band is what keeps the
        difference honest. A model asked for five integer percentages returns 95 or 105 often
        enough that rejecting those would spend a retry on arithmetic rather than on judgement,
        and the reallocation is deterministic: `question_shape.largest_remainder` is the same
        apportionment `focus.reserve` and `syllabus.plan_grid` already use, so there is one
        rounding rule in this codebase rather than two.

        Outside the band there is nothing to round. A set of weights summing to 40 or to 300 is
        not a distribution that drifted, it is a model that answered a different question, and
        the honest response is to fail validation so `generate_structured` retries.
        """
        from app.data.question_shape import largest_remainder  # noqa: PLC0415

        raw = sum(t.weight for t in self.topics)
        if not (80 <= raw <= 120):
            raise ValueError(f"topic weights sum to {raw}, which is not a distribution")
        if raw != 100:
            shares = {t.name: float(t.weight) for t in self.topics}
            fixed = largest_remainder(shares, 100)
            for topic in self.topics:
                topic.weight = fixed[topic.name]
        # largest_remainder can zero an area that rounded to nothing. An area with no weight
        # is an area the planner will never allocate a question to, so it is not an area.
        self.topics = [t for t in self.topics if t.weight > 0]
        if len(self.topics) < 4:
            raise ValueError("fewer than four areas survived normalisation")
        if not any(t.behavioural for t in self.topics):
            raise ValueError("the behavioural area rounded away to nothing")
        total = sum(t.weight for t in self.topics)
        if total != 100:
            raise ValueError(f"weights still sum to {total} after normalisation")
        return self


#: Words that open a question. Lifted from the same idea as `syllabus._check_phrase` — the
#: obvious way past a "no question mark" rule is to delete the mark.
_INTERROGATIVES = frozenset(
    {
        "what", "why", "how", "when", "where", "which", "who", "whom", "whose",
        "is", "are", "do", "does", "did", "can", "could", "would", "should",
        "explain", "describe", "define", "tell", "give", "name", "list", "walk",
        "discuss", "compare", "state", "write",
    }
)
