"""
Events package — events/__init__.py
"""

from .base import (
    # Enum
    EventType,
    # Base
    BaseEvent,
    # Interview lifecycle
    InterviewStartedEvent,
    InterviewStartedPayload,
    InterviewCompletedEvent,
    InterviewCompletedPayload,
    InterviewAbandonedEvent,
    InterviewAbandonedPayload,
    # In-session
    QuestionAskedEvent,
    QuestionAskedPayload,
    AnswerSubmittedEvent,
    AnswerSubmittedPayload,
    AnswerEvaluatedEvent,
    AnswerEvaluatedPayload,
    FollowUpTriggeredEvent,
    FollowUpTriggeredPayload,
    # Reports
    ReportGeneratedEvent,
    ReportGeneratedPayload,
    ReportExportedEvent,
    ReportExportedPayload,
    # Resume
    ResumeUploadedEvent,
    ResumeUploadedPayload,
    ResumeParsedEvent,
    ResumeParsedPayload,
    ResumeParseFailedEvent,
    ResumeParseFailedPayload,
    # System
    AIProviderErrorEvent,
    AIProviderErrorPayload,
)
from .emitter import EventEmitter, get_event_emitter
from .event_bus import EventBus, get_event_bus, initialize_event_bus

__all__ = [
    "EventType",
    "BaseEvent",
    "InterviewStartedEvent",
    "InterviewStartedPayload",
    "InterviewCompletedEvent",
    "InterviewCompletedPayload",
    "InterviewAbandonedEvent",
    "InterviewAbandonedPayload",
    "QuestionAskedEvent",
    "QuestionAskedPayload",
    "AnswerSubmittedEvent",
    "AnswerSubmittedPayload",
    "AnswerEvaluatedEvent",
    "AnswerEvaluatedPayload",
    "FollowUpTriggeredEvent",
    "FollowUpTriggeredPayload",
    "ReportGeneratedEvent",
    "ReportGeneratedPayload",
    "ReportExportedEvent",
    "ReportExportedPayload",
    "ResumeUploadedEvent",
    "ResumeUploadedPayload",
    "ResumeParsedEvent",
    "ResumeParsedPayload",
    "ResumeParseFailedEvent",
    "ResumeParseFailedPayload",
    "AIProviderErrorEvent",
    "AIProviderErrorPayload",
    "EventEmitter",
    "get_event_emitter",
    "EventBus",
    "get_event_bus",
    "initialize_event_bus",
]
