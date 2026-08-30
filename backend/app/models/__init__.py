"""
Models package — models/__init__.py

Import all models here to ensure they are registered with SQLAlchemy's
declarative registry before Alembic introspects the metadata.
"""

from .activity import ActivityLog
from .ai_cache import AICache
from .ai_usage import AIUsage  # TEMPORARY — token counter
from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from .billing import CreditEvent, OfferBanner, Referral, ReferralCode, UserPlan
from .company import Company, InterviewTrack, QuestionCategory
from .consent import ConsentEvent
from .prep import PrepProgress
from .progress import RatingEvent
from .question import FollowUpQuestion, Question, Subtopic, Topic
from .report import Report, ReportJob, ResumeFile
from .research import CompanyResearch
from .security import UserSession
from .session import Answer, InterviewSession, Score, VoiceTranscript
from .system import AuditLog, SystemPrompt
from .tts_usage import TTSUsage
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
    "ReportJob",
    "CompanyResearch",
    "ResumeFile",
    # Consent (DPDP §6 evidence ledger)
    "ConsentEvent",
    # System
    "AuditLog",
    "SystemPrompt",
    # Billing
    "UserPlan",
    "CreditEvent",
    "OfferBanner",
    "ReferralCode",
    "Referral",
    # Security
    "UserSession",
    # Activity
    "ActivityLog",
    # Progress
    "RatingEvent",
    # AI cache
    "AICache",
    # Speech cost ledger
    "TTSUsage",
]
