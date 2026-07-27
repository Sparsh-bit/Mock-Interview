"""
Application Settings — core/config.py

All configuration is read from environment variables via Pydantic BaseSettings.
The application will NOT start if required variables are missing — this is intentional.
There are no default values for secrets.

Load order:
  1. OS environment
  2. .env file (if present)
  3. .env.{ENVIRONMENT} file (if present, e.g. .env.production)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Single source of truth for all application configuration.
    Never access os.environ directly in application code — always use settings.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    APP_NAME: str = "InterviewOS"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "console"

    # ── API ───────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    REQUEST_TIMEOUT_SECONDS: int = 30
    MAX_UPLOAD_SIZE_MB: int = 10

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        description="PostgreSQL connection string. Must start with postgresql+asyncpg://",
    )

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure the URL uses the asyncpg driver."""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False  # Set True to log all SQL queries

    # ── Redis ─────────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL (Upstash: rediss://...)",
    )
    REDIS_MAX_CONNECTIONS: int = 20
    REDIS_DEFAULT_TTL_SECONDS: int = 3600

    # ── Supabase ──────────────────────────────────────────────────────────
    SUPABASE_URL: str = Field(description="Your Supabase project URL")
    SUPABASE_ANON_KEY: str = Field(description="Supabase anon/public key")
    SUPABASE_SERVICE_KEY: str = Field(description="Supabase service role key (server-side only)")
    SUPABASE_JWT_SECRET: str = Field(description="JWT secret from Supabase dashboard → Settings → API")

    # ── Auth ──────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # ── AI Provider ───────────────────────────────────────────────────────
    AI_PROVIDER: str = Field(
        default="glm",
        description="Primary AI provider: glm | nvidia | openai | anthropic | gemini | local",
    )
    AI_FALLBACK_PROVIDER: str = Field(
        default="nvidia",
        description=(
            "Secondary provider tried when the primary fails or returns "
            "unusable output. Empty string disables fallback. Must differ "
            "from AI_PROVIDER and have its own API key configured."
        ),
    )

    # GLM — ZhipuAI's own API (default provider)
    GLM_API_KEY: str = Field(default="", description="API key")
    GLM_MODEL: str = Field(default="glm-4-flash", description="GLM model name")
    GLM_BASE_URL: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4",
        description="GLM (ZhipuAI) base URL"
    )

    # NVIDIA NIM — alternate provider, same OpenAI-compatible shape as GLM
    NVIDIA_API_KEY: str = Field(default="", description="NVIDIA NIM API key")
    NVIDIA_MODEL: str = Field(
        default="nvidia/nemotron-3-ultra-550b-a55b", description="NVIDIA NIM model name"
    )
    NVIDIA_BASE_URL: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="NVIDIA NIM base URL"
    )

    # OpenAI (future)
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key (future)")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini", description="OpenAI model name")

    # Anthropic — Claude (paid; cost-controlled, see services/ai/anthropic_provider.py)
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic API key")
    ANTHROPIC_MODEL: str = Field(
        default="claude-sonnet-5",
        description=(
            "Claude model id. Sonnet 5 is the cost/quality pick for this app "
            "($3/$15 per MTok, intro $2/$10 through 2026-08-31). Note Sonnet 5 "
            "rejects temperature/top_p/top_k, so the provider drops them."
        ),
    )
    ANTHROPIC_PROMPT_CACHING: bool = Field(
        default=True,
        description=(
            "Mark the system prompt as cacheable. Repeat calls with an identical "
            "system prefix bill input at ~0.1x. Only prefixes >=1024 tokens cache "
            "on Sonnet 5; shorter ones are a silent no-op (no error, no benefit)."
        ),
    )
    ANTHROPIC_MAX_OUTPUT_TOKENS: int = Field(
        default=4096,
        description=(
            "Hard per-request ceiling on output tokens, applied after each call "
            "site's own max_tokens. Output is 5x the price of input, so this is "
            "the main guard against a single runaway response burning the budget."
        ),
    )

    # ── Storage ───────────────────────────────────────────────────────────
    SUPABASE_STORAGE_BUCKET_RESUMES: str = "resumes"
    SUPABASE_STORAGE_BUCKET_REPORTS: str = "reports"
    SUPABASE_STORAGE_BUCKET_AVATARS: str = "avatars"

    # ── Feature flags ─────────────────────────────────────────────────────
    FEATURE_VOICE_INTERVIEW: bool = False
    FEATURE_ADMIN_PANEL: bool = False
    FEATURE_ANALYTICS: bool = True

    # ── Rate limiting ─────────────────────────────────────────────────────
    RATE_LIMIT_INTERVIEW_PER_HOUR: int = 10
    RATE_LIMIT_AI_REQUESTS_PER_MINUTE: int = 30
    RATE_LIMIT_CODE_EXEC_PER_MINUTE: int = 20

    # ── Code execution (self-hosted Piston) ───────────────────────────────
    PISTON_BASE_URL: str = Field(
        default="http://localhost:2000/api/v2",
        description="Piston code-execution API base URL (self-hosted via docker-compose)",
    )

    # ── Sentry (error tracking, optional) ─────────────────────────────────
    SENTRY_DSN: str = Field(default="", description="Sentry DSN for error tracking")

    # ── Computed properties ───────────────────────────────────────────────

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns the application settings singleton.
    Cached after first call — safe to call multiple times.
    """
    return Settings()


# Module-level alias for ergonomic imports:
#   from app.core.config import settings
settings: Settings = get_settings()
