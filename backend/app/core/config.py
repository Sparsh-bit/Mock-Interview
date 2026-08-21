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
    #: Supabase issues aud="authenticated" for a signed-in user. Verified rather than
    #: skipped: without it, a token minted for a different audience — a service role, or
    #: another project sharing a secret — satisfies this API as an ordinary user.
    SUPABASE_JWT_AUDIENCE: str = "authenticated"
    #: Accept a JWT WITHOUT verifying its signature when no key is available. A total
    #: auth bypass, so it is off by default and additionally requires
    #: ENVIRONMENT=development — see _unverified_jwt_allowed in core/security.py. The
    #: previous behaviour keyed off ENVIRONMENT alone, which DEFAULTS to development, so
    #: a deployment that forgot to set it accepted forged tokens the first time the JWKS
    #: endpoint hiccuped. Never set this outside local development.
    ALLOW_UNVERIFIED_JWT: bool = False
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

    #: Server connections this process keeps open. The real ceiling is
    #: (DB_POOL_SIZE + DB_MAX_OVERFLOW) x replica count, measured against Postgres's
    #: own max_connections — so raising this to serve more users is exactly backwards
    #: past a point: it exhausts the database instead of the pool. Behind Supabase's
    #: transaction pooler (port 6543) keep these SMALL and let the pooler multiplex;
    #: 5 + 10 across four replicas is 60 server connections, which a paid Supabase
    #: instance serves comfortably.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    #: Seconds a request waits for a free connection before failing. Deliberately
    #: NOT large: a request queued 30s behind a saturated pool has already lost the
    #: user, and holding it there consumes a worker that could serve someone else.
    DB_POOL_TIMEOUT: int = 30
    #: Recycle connections after this long. Must sit BELOW any pooler or load
    #: balancer idle timeout, or the first request after a quiet spell hits a socket
    #: the other end already closed. Supabase's pooler cuts idle connections well
    #: before 30 minutes, so 25 minutes is the safe side of it.
    DB_POOL_RECYCLE: int = 1500
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
            "Kill switch for prompt caching. Caching is now OPT-IN PER CALL "
            "(ProviderRequest.cache_system), so this being on does not cache anything "
            "by itself — a call site has to declare that its system block is "
            "byte-identical across requests. That distinction is the whole point: this "
            "setting used to mean 'cache every system prompt', which was strictly worse "
            "than not caching, because PromptBuilder.chat substitutes per-request "
            "variables INTO the system template, so every call was a cache WRITE at "
            "1.25x input and never a read. Only gd_panel_turn opts in today: gd_panel.md "
            "is loaded verbatim via chat_static with the per-round content in the user "
            "message, and a GD round re-sends that same ~2100-token rulebook up to 26 "
            "times. Set this false only to rule caching out while debugging a cost or "
            "correctness question."
        ),
    )
    INTERVIEW_QUESTION_COUNT: int = Field(
        default=12,
        ge=4,
        le=25,
        description=(
            "How many questions a planned interview actually asks. This is the "
            "number the UI must advertise — a track's `question_count` is the "
            "size of its question BANK, not the interview length, and showing "
            "that made a 12-question interview look like a 20-question one."
        ),
    )
    INTERVIEW_MAX_CROSS_QUESTIONS: int = Field(
        default=4,
        ge=0,
        le=10,
        description="Max live follow-up cross-questions injected during an interview.",
    )
    AI_DAILY_BUDGET_USD: float = Field(
        default=60.0,
        description=(
            "CIRCUIT BREAKER on metered AI spend per UTC day, across all users. Not a "
            "daily allowance — that is AI_USER_DAILY_BUDGET_USD. This exists to stop a "
            "runaway loop or a compromised key draining the balance overnight, so it "
            "should sit well ABOVE a busy legitimate day and tripping it should page "
            "somebody. It was 2.0, which is about nine full interviews across the whole "
            "product, so it was doing duty as an allowance and one user (or one test "
            "run) could starve everybody until midnight UTC. 60 is roughly 400 GD rounds "
            "or 260 interviews a day; raise it as traffic grows and keep the per-user cap "
            "as the thing that actually rations. 0 disables it (not recommended). See "
            "docs/AI-COST-MODEL.md for the per-feature arithmetic."
        ),
    )
    AI_USER_DAILY_BUDGET_USD: float = Field(
        default=1.20,
        description=(
            "Per-user metered AI spend per UTC day. THIS is the allowance. When a user "
            "exceeds it their calls fall through to the free provider for the rest of the "
            "day — nothing breaks and no feature is blocked, they are on the standby "
            "model. Scoped by the authenticated user from the contextvar core/security.py "
            "sets, so unauthenticated or background work counts only against the global "
            "breaker. 1.20 is about three full mock interviews or eight group discussions "
            "in a day, which is more practice than anyone does honestly and cheap enough "
            "to carry a thousand users. 0 disables per-user metering. This is the seam the "
            "credit/subscription system will replace — see docs/TEMPORARY-token-counter.md."
        ),
    )
    # ── TEMPORARY: token counter ─────────────────────────────────────────
    # Removed with the rest of the ledger once credits and subscriptions land.
    # See docs/TEMPORARY-token-counter.md.
    AI_USAGE_LEDGER_ENABLED: bool = Field(
        default=True,
        description=(
            "TEMPORARY. Record one row per billed AI provider call so per-feature "
            "token use and cost can be measured before pricing a credit system. "
            "Writes are best-effort and can never fail a request. Set false to "
            "switch the ledger off without a deploy; the admin view then 404s."
        ),
    )
    ANTHROPIC_MAX_OUTPUT_TOKENS: int = Field(
        # Must stay >= the largest call-site budget, which is the report's
        # _REPORT_TOKENS_MAX. This ceiling is applied AFTER each call site's own
        # max_tokens, so a ceiling below the report budget silently clamps the
        # response and the JSON truncates — which is the exact failure that made
        # reports come back unscored. tests/test_report_cost_policy.py asserts the
        # relationship, and it caught this when the report budget was raised to
        # 12,000 and this was left at 8,192.
        default=12_288,
        description=(
            "Hard per-request ceiling on output tokens, applied after each call "
            "site's own max_tokens. Output is 5x the price of input, so this is "
            "the main guard against a single runaway response burning the budget. "
            "8192, not 4096: a full interview report for a 16-question session "
            "measures ~5.1k output tokens, so 4096 silently truncated every one "
            "of them mid-JSON -- the response then failed validation and the "
            "candidate got an unscored placeholder. This is a SAFETY ceiling for "
            "runaway responses, not a budget knob; it must sit above what the "
            "largest legitimate response needs, or it converts a cost control "
            "into a correctness bug. Per-call cost is controlled at the call "
            "sites (which set their own, lower max_tokens) and by "
            "AI_DAILY_BUDGET_USD."
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
    #: Seconds a LIVE question may spend waiting on the AI before the interview serves a
    #: cached or banked one instead.
    #:
    #: THIS EXISTS BECAUSE THERE WAS NO LIMIT AT ALL. Plan generation has had a 110s budget
    #: for a long time; per-question generation had none, and the GLM client's own read
    #: timeout is 180 seconds. So a slow provider mid-interview could leave a candidate
    #: looking at nothing for three minutes, with no way to tell whether the software had
    #: died. Reported as "when the api gets slower or takes time to respond then try to pick
    #: up some questions from the vector database that will not break the flow".
    #:
    #: 18 SECONDS, and the number is a judgement about the room rather than about the vendor.
    #: A generated question is better than a banked one — it is aimed at what the candidate
    #: just revealed — so this should not be so tight that it throws away good questions for
    #: a provider having a slow second. But an interviewer who goes silent for twenty seconds
    #: has already broken the illusion, and past that point a *worse but immediate* question
    #: is the better product. The fallback is not a failure state: the bank and the shared
    #: pool are real questions for this role.
    #:
    #: Raising this trades interview fluency for question quality; lowering it trades the
    #: other way and leans harder on the cache. Zero disables the budget, which restores the
    #: old unbounded behaviour and is not recommended.
    INTERVIEW_QUESTION_AI_BUDGET_SECONDS: float = 18.0
    #: Seconds a GD panel turn may spend waiting on the AI before the round moves on without
    #: it.
    #:
    #: REPORTED AS "the gd is facing the response timed out issue", and there was NOTHING
    #: bounding it. Not one `asyncio.wait_for` anywhere in api/v1/gd.py, `attempts_per_provider`
    #: of 2, and a provider read timeout of 180 seconds — so a slow provider could hold a
    #: single turn for up to six minutes. The client gave up long before that and showed a
    #: timeout, while the server was still generating a contribution nobody would ever see.
    #:
    #: TIGHTER THAN THE INTERVIEW'S 18s, because a group discussion is less forgiving than an
    #: interview. An interview is turn-taking — the candidate expects to wait after they finish
    #: speaking. A GD runs on an autonomous clock with three people talking, so a gap reads as
    #: the discussion having died rather than as somebody thinking, and the candidate starts
    #: talking over it.
    #:
    #: On expiry the round returns an empty turn, which is the same path a provider outage
    #: already used and which the caller already handles: the discussion continues and the next
    #: tick asks again. A missing contribution is invisible in a conversation between three
    #: people; a twelve-second silence is not.
    GD_TURN_AI_BUDGET_SECONDS: float = 12.0
    RATE_LIMIT_INTERVIEW_PER_HOUR: int = 10
    RATE_LIMIT_AI_REQUESTS_PER_MINUTE: int = 30
    RATE_LIMIT_CODE_EXEC_PER_MINUTE: int = 20
    #: Report generations per hour, per user. The most expensive call in the app by a wide
    #: margin — roughly 13.5 cents for a full interview — so it needs a ceiling.
    #:
    #: Only real GENERATIONS count. The endpoint doubles as the client's read path (it is
    #: idempotent, so useReport POSTs to it), and the limiter used to be a route dependency
    #: that charged for every call including the ones that just returned a finished report.
    #: Six an hour then meant a candidate re-reading their own report six times was locked
    #: out. The check now sits at the point a model call is about to be made — see
    #: api/v1/reports.py — so reads are free.
    #:
    #: Raised from 6 to 15 as well, because a generation that degrades to the unscored
    #: placeholder is legitimately retried, and each retry is a real attempt. Fifteen still
    #: bounds a runaway loop and no honest candidate reaches it.
    RATE_LIMIT_REPORT_PER_HOUR: int = 15
    #: Authenticated read endpoints (standing, profile, stats) per minute per user.
    #: 120 is two a second sustained — far above anything the UI does, including a
    #: dashboard that refetches on focus — but it stops an authenticated retry loop from
    #: issuing unbounded queries against a shared database.
    RATE_LIMIT_READ_PER_MINUTE: int = 120

    # ── Neural text-to-speech ────────────────────────────────────────────────
    #
    # OFF by default, and that is a cost decision rather than caution. TTS is priced per
    # CHARACTER, and on ElevenLabs' Creator tier a single GD round of neural speech costs
    # about twelve times every AI call in that round combined — see the table in
    # services/tts/base.py and docs/AI-COST-MODEL.md. The browser's speechSynthesis is free and
    # already works; this is a paid upgrade to how it sounds, so it has to be switched on
    # deliberately by somebody who has looked at the numbers.
    TTS_ENABLED: bool = False
    TTS_PROVIDER: str = Field(
        default="elevenlabs",
        description=(
            "Which vendor. 'elevenlabs' is the best-sounding and the most expensive. Azure "
            "and Google Neural are roughly 14x cheaper per character AND have native en-IN "
            "voices (Neerja, Prabhat) — for Indian campus practice an authentic accent is "
            "usually worth more than emotional range. Add one as a new module in "
            "services/tts/ and a branch in factory.py; nothing else changes."
        ),
    )
    FISH_API_KEY: str = Field(
        default="",
        description=(
            "Fish Audio API key. Server-side only, never sent to the browser. NOTE: Fish "
            "bills API credit SEPARATELY from platform credit — a valid key on an account "
            "with no API credit returns HTTP 402. Top up at fish.audio/app/developers."
        ),
    )
    FISH_MODEL: str = Field(
        default="s1",
        description=(
            "Fish synthesis backend, sent as a HEADER rather than a body field.\n\n"
            "IT WAS 's2.1-pro-free' AND THAT VALUE NOW HANGS. The note here used to say the "
            "free tier 'returns real audio on a zero-credit key in ~3.5s', which was true when "
            "it was written and is not true any more — retested live and 's2.1-pro-free' does "
            "not answer at all: the TCP connect and the TLS handshake succeed and then the "
            "request sits until the client gives up. Measured at 35s and at 60s with no "
            "response either time.\n\n"
            "THAT IS WORSE THAN A REFUSAL, AND IT IS WHY THE VOICES WERE REPORTED AS "
            "'CHANGING TO THE OLDER VOICES'. Every real backend answers HTTP 402 in under a "
            "second, which the client turns into an immediate, permanent fall back to browser "
            "speech. A retired backend that hangs instead makes the first line of an interview "
            "wait out the 12s timeout in silence before falling back — so the panel starts on "
            "one voice and finishes on another, and nothing in the logs says why, because "
            "httpx raises ReadTimeout with an EMPTY message.\n\n"
            "'s1' is Fish's current model. Verified live: it answers in under a second. On a "
            "key with no API credit that answer is a 402, which is the honest state of the "
            "account rather than a hang — and API credit is billed SEPARATELY from platform "
            "credit at fish.audio/app/developer, so a funded-looking subscription can still be "
            "refused. 'speech-1.6', 'speech-1.5' and 's1-mini' all also answer in under a "
            "second and are equally valid here.\n\n"
            "Never set this to a backend that has been retired. A wrong value that 402s costs "
            "one round of browser voices; a wrong value that hangs costs a timeout per "
            "interview and looks like an intermittent bug."
        ),
    )
    ELEVENLABS_API_KEY: str = Field(default="", description="Server-side only. Never sent to the browser.")
    ELEVENLABS_MODEL: str = Field(
        default="eleven_flash_v2_5",
        description=(
            "flash_v2_5 bills at HALF the credits per character and answers in ~75ms rather "
            "than several hundred. Both matter in a live discussion. multilingual_v2 is "
            "richer and is the right choice only for pre-rendered audio."
        ),
    )
    ELEVENLABS_TIER: str = Field(
        default="creator",
        description=(
            "Your subscription tier — free | starter | creator | pro | scale | business. Used "
            "ONLY to estimate cost per character, which varies nearly twofold across tiers. "
            "Setting it wrong makes the spend log wrong, not the synthesis."
        ),
    )
    TTS_VOICE_IDS: str = Field(
        default="",
        description=(
            "Speaker-to-voice map, as 'Riya:voiceid,Arjun:voiceid,Meera:voiceid,"
            "interviewer:voiceid'. Names must match PANELISTS in api/v1/gd.py. Resolved "
            "server-side so a client cannot choose its own voice — which is what keeps Meera "
            "female, and on a metered vendor also what stops a caller picking an expensive "
            "model. Voice ids are account-specific, so they live in the environment rather "
            "than the repo."
        ),
    )
    TTS_DAILY_BUDGET_USD: float = Field(
        default=5.0,
        description=(
            "Circuit breaker on speech spend per UTC day, across all users. Separate from "
            "AI_DAILY_BUDGET_USD because characters and tokens are not interchangeable and "
            "one silently eating the other is how a bill becomes a surprise. Past it, "
            "everyone falls back to browser speech and nothing breaks. 0 disables the cap."
        ),
    )
    TTS_CACHE_TTL_SECONDS: int = Field(
        default=60 * 60 * 24 * 14,
        description=(
            "How long synthesised audio is cached. Fourteen days because the interview reads "
            "questions from a FIXED bank — the same ~37 for every candidate — so after the "
            "first user those are free. That cache is worth far more than the GD one, where "
            "every contribution is unique text and will never hit."
        ),
    )
    TTS_RATE_LIMIT_PER_HOUR: int = Field(
        default=200,
        description=(
            "Synthesis requests per user per hour. A GD round is up to ~40 utterances and an "
            "interview ~16, so this covers several rounds while stopping a loop from spending "
            "a month's character allowance in an afternoon."
        ),
    )

    # ── Payments (Razorpay) ───────────────────────────────────────────────
    #
    # All three default to empty, and that is deliberate: a deployment with no keys must run
    # normally with the free tier working and only the checkout route refusing. Making these
    # required would mean nobody can run the app locally without a payments account, and
    # giving them fake defaults would mean an unpayable checkout reaching production looking
    # like a working one.
    RAZORPAY_KEY_ID: str = Field(
        default="",
        description=(
            "Razorpay public key id. This one is MEANT to reach the browser — the checkout "
            "widget needs it. Empty disables the purchase route with a 503."
        ),
    )
    RAZORPAY_KEY_SECRET: str = Field(
        default="",
        description="Razorpay secret. Server-side only — never returned by any endpoint.",
    )
    # ── Captcha (Cloudflare Turnstile) ───────────────────────────────────────────────
    #
    # Only consulted by offers that set `requires_captcha`. Unset means those offers REFUSE
    # rather than waive the requirement — see services/billing/captcha.py. Everything else in
    # the app is unaffected, so a deployment with no Turnstile account works normally as long
    # as no offer asks for one.
    TURNSTILE_SECRET_KEY: str = Field(
        default="",
        description=(
            "Cloudflare Turnstile secret. Server-side only. The matching SITE key is public "
            "by design and belongs in the frontend as NEXT_PUBLIC_TURNSTILE_SITE_KEY."
        ),
    )

    RAZORPAY_WEBHOOK_SECRET: str = Field(
        default="",
        description=(
            "Secret Razorpay signs webhook bodies with. SEPARATE from the API secret and set "
            "independently in their dashboard; using the wrong one makes every webhook fail "
            "verification, which presents as payments succeeding and plans never upgrading. "
            "Empty means the webhook rejects everything, which is the correct closed default "
            "for a public URL."
        ),
    )

    # ── Code execution (self-hosted Piston) ───────────────────────────────
    PISTON_BASE_URL: str = Field(
        default="http://localhost:2000/api/v2",
        description="Piston code-execution API base URL (self-hosted via docker-compose)",
    )
    CODE_EXEC_PROVIDER: str = Field(
        default="judge0",
        description=(
            "Code runner: judge0 | piston. Judge0 CE is the default because it "
            "is free, needs no key, and works on hosts where we cannot run "
            "privileged containers. Piston is for local dev via docker-compose "
            "(its public API went whitelist-only in Feb 2026 and returns 401)."
        ),
    )
    JUDGE0_BASE_URL: str = Field(
        default="https://ce.judge0.com",
        description="Judge0 CE base URL. Self-host or use a RapidAPI host for higher limits.",
    )
    JUDGE0_API_KEY: str = Field(
        default="",
        description="Optional RapidAPI key. Empty = use the free public CE instance.",
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
