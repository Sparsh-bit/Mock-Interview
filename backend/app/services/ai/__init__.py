"""
AI Services package — services/ai/__init__.py

Public API for the AI provider abstraction layer.

All AI-related imports in the application should come from this package,
not from individual sub-modules.
"""

from .base_provider import (
    BaseAIProvider,
    ProviderError,
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
)
from .json_validator import AIValidationError, JSONValidator
from .prompt_builder import PromptBuilder
from .provider_factory import (
    close_ai_provider,
    get_ai_provider,
    initialize_ai_provider,
    register_provider,
)
from .response_parser import ResponseParser
from .schemas import (
    AnswerEvaluation,
    GeneratedQuestion,
    ImprovementResourceItem,
    ImprovementRoadmapItem,
    InterviewerResponse,
    InterviewState,
    QuestionAnalysisItem,
    ReportGeneratorResponse,
)

__all__ = [
    # Base types
    "BaseAIProvider",
    "ProviderError",
    "ProviderMessage",
    "ProviderRequest",
    "ProviderResponse",
    # Validation
    "AIValidationError",
    "JSONValidator",
    # Parsing and building
    "PromptBuilder",
    "ResponseParser",
    # Response schemas
    "AnswerEvaluation",
    "GeneratedQuestion",
    "InterviewState",
    "InterviewerResponse",
    "ImprovementResourceItem",
    "ImprovementRoadmapItem",
    "QuestionAnalysisItem",
    "ReportGeneratorResponse",
    # DI factory
    "get_ai_provider",
    "register_provider",
    # Lifespan lifecycle (call from app/main.py startup/shutdown)
    "initialize_ai_provider",
    "close_ai_provider",
]
