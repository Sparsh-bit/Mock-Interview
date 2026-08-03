"""
Models package — models/__init__.py

Import all models here to ensure they are registered with SQLAlchemy's
declarative registry before Alembic introspects the metadata.
"""

from .activity import ActivityLog
from .ai_usage import AIUsage  # TEMPORARY — token counter
from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from .company import Company, InterviewTrack, QuestionCategory
from .prep import PrepProgress
from .question import FollowUpQuestion, Question, Subtopic, Topic
from .report import Report, ResumeFile
from .research import CompanyResearch
from .session import Answer, InterviewSession, Score, VoiceTranscript
from .system import AuditLog, SystemPrompt
from .user import Profile, User

__all__ = [
    # TEMPORARY — token counter
    "AIUsage",
    # Base
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    # User
    "User",
    "Profile",
    # Company
    "Company",
    "InterviewTrack",
    "QuestionCategory",
    # Question
    "Topic",
    "Subtopic",
    "Question",
    "FollowUpQuestion",
    # Session
    "InterviewSession",
    "Answer",
    "Score",
    "VoiceTranscript",
    # Report
    "PrepProgress",
    "Report",
    "CompanyResearch",
    "ResumeFile",
    # System
    "AuditLog",
    "SystemPrompt",
    # Activity
    "ActivityLog",
]
