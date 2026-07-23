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

from pydantic import AnyHttpUrl, Field, PostgresDsn, field_validator
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
        description="Active AI provider: glm | openai | anthropic | gemini | local",
    )

    # GLM (NVIDIA NIM or ZhipuAI) — default provider
    GLM_API_KEY: str = Field(default="", description="API key")
    GLM_MODEL: str = Field(default="glm-4-flash", description="GLM model name")
    GLM_BASE_URL: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4",
        description="GLM base URL (override for NVIDIA NIM)"
    )

    # OpenAI (future)
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key (future)")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini", description="OpenAI model name")

    # Anthropic (future)
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic API key (future)")
    ANTHROPIC_MODEL: str = Field(default="claude-3-5-haiku-latest")

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
