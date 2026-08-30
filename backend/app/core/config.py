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
    APP_NAME: str = "Hotseat"
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
    #: The pooler's own limit on simultaneous CLIENT connections, off the Supabase
    #: dashboard. Startup checks (DB_POOL_SIZE + DB_MAX_OVERFLOW) x WEB_REPLICA_COUNT
    #: against it and WARNS — never crashes; an over-subscribed pool still serves every
    #: request that gets a connection, and refusing to boot would turn a degradation that
    #: might never be reached into a certain outage, during a deploy.
    #:
    #: NO DEFAULT, for the same reason as REDIS_CONNECTION_CEILING: every provider and plan
    #: has a different number, they change, and a guessed ceiling is a check that is
    #: confidently wrong. 0 means "not configured" and startup says exactly that.
    DB_CONNECTION_CEILING: int = 0

    # ── Deployment topology ───────────────────────────────────────────────
    #: How many copies of this process the platform runs. NOT read by the app to
    #: change behaviour — it is read by the startup audits that multiply a per-process
    #: budget by it, because every connection ceiling in this file is a PER-FLEET
    #: number that the code can only see one Nth of. Keep it equal to the replica
    #: count in render.yaml; a stale value here makes the audits silently wrong in
    #: the optimistic direction.
    WEB_REPLICA_COUNT: int = 1

    # ── Redis ─────────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL. Managed providers require TLS: rediss://...",
    )
    #: PER PROCESS. The number that matters to a managed provider is this times
    #: WEB_REPLICA_COUNT, checked at startup against REDIS_CONNECTION_CEILING.
    REDIS_MAX_CONNECTIONS: int = 20
    REDIS_DEFAULT_TTL_SECONDS: int = 3600
    #: The provider's own per-plan limit on simultaneous client connections. There is
    #: deliberately NO default: every provider and plan has a different number, they
    #: change, and a guessed ceiling produces an audit that is confidently wrong. 0
    #: means "not configured" and the startup audit says so rather than inventing one.
    #: Read it off the plan page during cutover — docs/REDIS-CUTOVER.md §1.
    REDIS_CONNECTION_CEILING: int = 0
    #: Path to a CA bundle, for a provider that presents a certificate the system trust
    #: store does not chain to. Ignored for a plaintext redis:// URL, where redis-py's
    #: non-TLS Connection would reject the kwarg outright.
    REDIS_TLS_CA_CERTS: str | None = None
    #: Seconds between PINGs on an idle pooled connection. THE FAILOVER SETTING: when a
    #: managed provider promotes a replica, sockets to the old node stay open and look
    #: healthy until a command uses one. Without this the first request after every
    #: failover fails; with it redis-py checks the connection before handing it out.
    #: Must stay well below the provider's idle-connection timeout.
    REDIS_HEALTH_CHECK_INTERVAL_SECONDS: int = 30
    #: Hard deadline on the PING behind GET /api/v1/health. Connect timeout multiplied
    #: by retries plus backoff runs past 20s, and a health check that slow reads to the
    #: platform as a dead instance — so the liveness probe gets its own bound, separate
    #: from the retry budget that real traffic is allowed to spend.
    REDIS_HEALTH_PING_TIMEOUT_SECONDS: float = 3.0
    #: Retries redis-py makes per command before surfacing the error. Sized for a
    #: failover blip (seconds), not for an outage — the callers all degrade rather than
    #: break, so spending longer here would just hold a worker.
    REDIS_MAX_RETRIES: int = 3

    # ── Supabase ──────────────────────────────────────────────────────────
    SUPABASE_URL: str = Field(description="Your Supabase project URL")
    SUPABASE_ANON_KEY: str = Field(description="Supabase anon/public key")
    SUPABASE_SERVICE_KEY: str = Field(description="Supabase service role key (server-side only)")
    SUPABASE_JWT_SECRET: str = Field(description="JWT secret from Supabase dashboard → Settings → API")

    # ── Auth ──────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # ── AI Provider ───────────────────────────────────────────────────────
    # ── ANTHROPIC IS THE PRIMARY, AND GLM IS NOT RELIED ON ───────────────────────────
    #
    # The default used to be glm/nvidia, and a production log showed exactly what that
    # cost: glm answered 429 — "您的账户已达到速率限制", the account's own rate limit —
    # the nvidia fallback could not be constructed at all, and every report failed with
    # "the model was unreachable". A rate-limited primary behind a non-existent fallback
    # is a chain with nothing in it.
    #
    # GLM stays as the FALLBACK. That is the difference between not relying on it and
    # not having it: it is worth the most in exactly the case Anthropic cannot serve —
    # a daily spend cap, which is instant and lasts until midnight UTC — and worth
    # nothing the rest of the time, because it is never reached.
    #
    # A DEFAULT IS NOT PRODUCTION. If AI_PROVIDER is set explicitly in the host's
    # environment, that value wins and this line changes nothing there.
    AI_PROVIDER: str = Field(
        default="anthropic",
        description="Primary AI provider: anthropic | glm | nvidia | openai | gemini | local",
    )
    AI_FALLBACK_PROVIDER: str = Field(
        default="glm",
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

    # ── Burst rung: a free tier behind the paid chain ─────────────────────
    #
    # A THIRD provider, strictly after AI_PROVIDER and AI_FALLBACK_PROVIDER, reachable only
    # from calls that pass BOTH gates in services/ai/burst_rung.py: the CHEAP cost tier and
    # an explicit feature allowlist. It exists for the minutes when both paid providers are
    # refusing — a daily spend cap, a rate limit — and being answered by a weaker model beats
    # not being answered.
    #
    # IT IS NOT CAPACITY, and the free-tier numbers say so plainly. Groq's free plan for
    # openai/gpt-oss-20b is 30 RPM / 1,000 requests a day / 8,000 tokens a minute (verified
    # against console.groq.com/docs/rate-limits on 2026-08-30 — these change, so re-check
    # rather than trusting this line). A panel turn is ~3.5k tokens, so 8,000 TPM is about
    # TWO turns a minute, against the 3.25 a single live GD round generates. One round does
    # not fit. Treat it as a rung that catches a blip, never as headroom.
    #
    # Empty disables it entirely, which is the default: no key, no rung, no behaviour change.
    AI_BURST_PROVIDER: str = Field(
        default="",
        description=(
            "Optional free-tier provider appended AFTER the primary and fallback. Gated to "
            "the CHEAP cost tier and the allowlist in services/ai/burst_rung.py. Empty = off."
        ),
    )
    GROQ_API_KEY: str = Field(default="", description="Groq API key. Empty = rung disabled.")
    GROQ_MODEL: str = Field(
        default="openai/gpt-oss-20b",
        description=(
            "Groq model id. gpt-oss-20b is a plain instruction-following chat model with "
            "JSON mode and the largest free daily token allowance of the chat models "
            "(200k TPD); groq/compound* are agentic systems and a poorer fit for the "
            "structured single-shot calls this rung serves."
        ),
    )
    GROQ_BASE_URL: str = Field(
        default="https://api.groq.com/openai/v1",
        description="Groq's OpenAI-compatible endpoint — the same shape GLM and NVIDIA use.",
    )

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
    ANTHROPIC_CHEAP_MODEL: str = Field(
        default="",
        description=(
            "The model CostTier.CHEAP calls run on, for the features listed in "
            "services/ai/model_routing.CHEAP_MODEL_FEATURES. EMPTY means no routing: every "
            "call uses ANTHROPIC_MODEL, which is the behaviour this app has always had.\n\n"
            "EMPTY BY DEFAULT BECAUSE THE MEASUREMENT SAID SO, and the measurement is the "
            "whole point of this setting existing. 'claude-haiku-4-5' is $1/$5 per MTok "
            "against Sonnet 5's $3/$15, and on a nine-scenario panel-dialogue comparison it "
            "came out 60-70% cheaper at the same latency, with no schema failures and no "
            "invented speakers — genuinely good numbers.\n\n"
            "It also broke the panel's own rules. interview_panel.md says 'One or two "
            "sentences' and 'Twenty-five words'; across two independent runs Haiku produced "
            "SIX over-length lines out of roughly twenty-one each time (longest 46 and 41 "
            "words) where Sonnet produced ZERO, and once used the candidate's name in a turn "
            "explicitly told not to. On a wrong answer it explained the concept instead of "
            "asking the follow-up — which is precisely the lecturing that prompt was "
            "rewritten to stop, and that tests/test_panel_brevity.py exists to guard.\n\n"
            "So the routing is built, tested, and one value away from live; turning it on is "
            "a decision to accept a measured quality regression for a real saving, and that "
            "is not a default. See docs/AI-COST-MODEL.md for the full table and for what "
            "would have to change first."
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
    #: Public bucket for promo banner images uploaded from the offers admin.
    #:
    #: MUST BE A PUBLIC BUCKET, unlike resumes and reports. A banner is rendered by an <img>
    #: on the dashboard for every signed-in candidate, so a private bucket would mean minting
    #: a signed URL per view — an extra round trip on a page load, and a link that expires
    #: while the page is open. The content is a marketing image we are choosing to show
    #: everybody, so there is nothing here that a public URL leaks.
    SUPABASE_STORAGE_BUCKET_BANNERS: str = "banners"

    # ─── The promo banner image contract ────────────────────────────────────────────────
    #
    # THESE NUMBERS ARE DERIVED FROM THE CONTAINER, NOT PICKED. The banner renders inside the
    # dashboard's content column: `max-w-6xl` with `sm:px-8`, which is 1152 - 64 = 1088 CSS
    # pixels at its widest. Everything below follows from that one measurement, and the admin
    # form quotes these exact values so an upload cannot be a guess.

    #: The required aspect ratio, width / height. 3:1.
    #:
    #: Chosen so the banner is a strip rather than a block: at the full 1088px it is 363px
    #: tall, and on a 360px phone it is 120px — big enough for a promo code to be legible,
    #: small enough that it never pushes the dashboard's actual content below the fold. The
    #: render fixes this ratio in CSS, so an image of ANY size stays undistorted and aligned;
    #: matching it is what avoids a centre-crop.
    BANNER_ASPECT_RATIO: float = 3.0
    #: How far from 3:1 an upload may be and still be accepted, as a fraction.
    #:
    #: 2%. Export tools round: a designer working to 3:1 can hand back 2400x801, and refusing
    #: that would be pedantry that teaches the admin to ignore the requirement. Wide enough to
    #: absorb rounding, far too narrow to admit 16:9 (1.78) or 4:1 — both of which WOULD crop
    #: visibly.
    BANNER_ASPECT_TOLERANCE: float = 0.02
    #: The size to export at: 2400x800.
    #:
    #: 2400 is 2.2x the 1088px container, so the image is sharp on a 2x display with a little
    #: headroom. Quoted to the admin as "the" size because one exact number produces correct
    #: uploads where a range produces the smallest value in it.
    BANNER_RECOMMENDED_WIDTH: int = 2400
    #: The floor. Below this an image is upscaled by the browser and looks soft.
    #:
    #: 1200 is just above the 1088px container, so a 1200px image is still rendered at 1:1 or
    #: better on a standard display — soft on a retina screen, but never blurry-on-everything.
    BANNER_MIN_WIDTH: int = 1200
    #: Bytes. 500 KB.
    #:
    #: A 2400x800 WebP of a promo graphic is comfortably under 200 KB, and a PNG of flat art
    #: around 300 KB, so this accepts a correct export with room to spare while refusing the
    #: 4 MB camera JPEG that would otherwise sit at the top of every candidate's dashboard on
    #: a mobile connection.
    BANNER_MAX_BYTES: int = 500 * 1024

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
    #: Seconds the study-resource attachment may spend before the report is saved without it.
    #:
    #: THIS WAS UNBOUNDED AND IT IS WHY REPORTS STILL TIMED OUT AT 120s AFTER THE AI CALL WAS
    #: CAPPED. `attach_to_roadmap` loops over every roadmap item and calls `resolve`, which on a
    #: cache miss makes ANOTHER AI call — so a report with eight uncached topics paid eight
    #: sequential generations AFTER its own 85-second budget had already been spent. Nothing
    #: bounded the total, so the client's 120-second timeout arrived first and the candidate saw
    #: "Report Unavailable" for a report the server was still assembling.
    #:
    #: 10 seconds, because this is the least valuable part of the response. The block's own
    #: comment already says so: "An item still carries its topic, score gap and study-hours
    #: estimate without resources, which is most of its value; a report that failed to save has
    #: none of it." A warm cache returns in milliseconds, so this only ever bites the first
    #: report to ask for a given topic — and those writes are shared, so the next candidate
    #: benefits from work this one abandoned.
    # 4.0, down from 10.0, and this is a LATENCY decision measured rather than guessed.
    #
    # Study resources are attached to the roadmap after the report is generated. A curated or
    # cached topic resolves from the database in milliseconds; only an UNCACHED one costs an AI
    # call, and that call is both slow and the one most likely to fail — it timed out on both
    # of two measured end-to-end runs, so ten seconds was being added to the candidate's wait
    # on every report and buying nothing.
    #
    # Reports must be quick, and this is the cheapest ten seconds in the request to give back.
    # Nothing is lost that the candidate would notice: a roadmap item still carries its topic,
    # its score gap and its study-hours estimate without resources, and whichever discovery
    # calls DO finish write into the shared cache — so the resources arrive for the next
    # candidate on that topic either way.
    REPORT_RESOURCE_BUDGET_SECONDS: float = 4.0
    #: Seconds quiz generation may spend on the AI before the curated bank serves the quiz.
    #:
    #: REPORTED AS "the quizes is also not generating the request timeout error is comming",
    #: and the arithmetic made it inevitable. NOTHING bounded the server: `generate_structured`
    #: loops every provider with `attempts_per_provider=2`, and the fallback provider's read
    #: timeout is 180 seconds (provider_factory.py) — so one slow vendor could hold a single
    #: /quiz/start for minutes. The BROWSER gives up at 30 seconds (`DEFAULT_TIMEOUT_MS` in
    #: frontend/src/lib/api/client.ts, which the quiz call does not override). The client
    #: therefore always lost the race and showed a timeout while the server was still building
    #: a quiz nobody would ever receive.
    #:
    #: THE FALLBACK EXISTED AND COULD NOT REACH. `/quiz/start` already drops to the curated
    #: bank — 97 questions across 16 topics, no vendor, no network — but only on
    #: `AIProviderUnavailableError`. A provider that is SLOW rather than broken never raises
    #: that, so the one path that would have saved the request was unreachable in exactly the
    #: situation it was written for. Bounding the wait is what connects them.
    #:
    #: 20 SECONDS, chosen against the client's 30 and not against the model's comfort. It
    #: leaves ten seconds of headroom for the bank fill, the DB write and the network, so the
    #: candidate gets a complete quiz well before the browser would have given up. A quiz is
    #: also the most forgiving feature to fall back on: bank questions are curated, already
    #: served by /quiz/bank/start, and indistinguishable in shape from generated ones — the
    #: candidate loses freshness, not a quiz, and never sees an error.
    #:
    #: Zero disables the budget, restoring the old unbounded behaviour. Do not.
    QUIZ_GENERATION_BUDGET_SECONDS: float = 20.0
    #: Most questions one AI call may be asked to write before the quiz is split into
    #: concurrent batches.
    #:
    #: MEASURED, because this is a latency law rather than a preference: 5 questions took 8.9s,
    #: 7 took 11.0s, and 20 did not finish inside 20 seconds at all. Wall-clock scales with how
    #: many questions a single call has to write, so the maximum quiz size (20) could not be
    #: served inside any budget the browser will wait for — and since the client aborts at 30s,
    #: there was no room to raise the budget into either.
    #:
    #: Batching makes the wait the cost of the LARGEST batch instead of the sum, so a
    #: 20-question quiz costs about what a 7-question one does and actually gets generated
    #: rather than always falling through to the curated bank.
    #:
    #: 5, measured against the real provider on a full-size quiz: at a batch max of 7 a
    #: 20-question quiz took 15.0s of the 20s budget, and at 5 it took 11.9s. Both produce the
    #: whole quiz from the AI with zero duplicates, but the second leaves 8 seconds of headroom
    #: rather than 5 — enough for a retry inside `generate_structured` when one batch trips the
    #: validity check, and enough that a slower-than-usual afternoon degrades to a partial bank
    #: fill instead of losing the generated quiz entirely.
    #:
    #: Not smaller than that: each batch is a separate billed call with its own overhead, and
    #: below about five questions the per-call cost starts to dominate latency that is already
    #: comfortably inside the budget.
    #:
    #: Zero means "never batch", restoring the single-call behaviour that could not serve a
    #: full-size quiz inside the client's timeout at all.
    QUIZ_BATCH_MAX_QUESTIONS: int = 5
    #: Output-token ceiling for one on-demand "ideal answer" on the detailed-analysis page.
    #:
    #: MEASURED, and raised from a hardcoded 900 after that ceiling was found to be silently
    #: truncating the useful half of the response. A design question's full shape — the spoken
    #: answer plus `what_was_missing`, `key_points` and `verdict_line` — measures 2700-4100
    #: characters of JSON, around 700-1000 output tokens. At 900 the answer itself consumed the
    #: budget and the three coaching fields were cut off; the truncation salvage then recovered
    #: a valid object with those fields at their empty defaults, so the request SUCCEEDED while
    #: dropping the only part a candidate needed. Nothing errored and nothing was logged.
    #:
    #: 1400 covers the largest observed shape with headroom. Short conceptual answers are
    #: unaffected — they finish around 1500 characters and never approach either figure.
    MODEL_ANSWER_MAX_TOKENS: int = 1400
    #: Wall-clock cap on generating one ideal answer.
    #:
    #: Well inside a managed host's ~100s gateway cut, because a gateway 502 carries no CORS
    #: headers and reaches the browser as an opaque CORS error rather than as a failed request.
    #: Also inside the 90s the client allows for this specific call (see useGenerateModelAnswer),
    #: so the server always loses the race deliberately and returns a real error instead of
    #: having the connection cut from under it. Measured latency is 6-16s.
    MODEL_ANSWER_BUDGET_SECONDS: float = 45.0
    #: How many reports may be generating at once, per process.
    #:
    #: RAISED FROM A HARDCODED 4, because 4 could not survive a drive and the arithmetic says
    #: so plainly. A report is 24s for six answers and 31s for twelve, measured; a full
    #: twenty-answer report was measured at 48s. The generation budget covers QUEUE TIME PLUS
    #: GENERATION — deliberately, so a queued candidate gets an honest retry rather than a
    #: request that hangs past the gateway — so every second spent waiting for a slot is a
    #: second the model does not get.
    #:
    #: With four slots and ~35s a report, the fifth candidate waits ~35s, the ninth ~70s, and
    #: the twentieth is far past any budget. A cohort finishing their interviews together is
    #: exactly what a campus drive IS, so under the old value most of them got "Scoring took
    #: too long" — having never reached the model at all.
    #:
    #: 12 costs nothing that matters. Each in-flight report holds a ~17k-token prompt, so
    #: twelve is well under a megabyte of text; the database connection is released across the
    #: model call, so there is no pool pressure; and twelve concurrent completions is
    #: unremarkable for the provider. What it buys is a queue three times shorter: with ~35s a
    #: report, twelve slots clear roughly twenty reports a minute per process.
    #:
    #: PER PROCESS, so the real ceiling is this times the replica count. Raise it if a drive
    #: still queues, and watch `report_queue_wait_seconds` in the logs to know whether it is
    #: queueing or generation that is slow — they are different problems with different fixes.
    REPORT_CONCURRENCY: int = 12

    # ── Reports through the Message Batches API ──────────────────────────────
    #
    # Anthropic bills a batched request at HALF PRICE on both input and output. On a report
    # measured at $0.1233 that is −$0.062 — about 40% of a warm interview, and more than
    # every prompt-caching win in this codebase put together. docs/AI-COST-MODEL.md names it
    # the single largest saving left, and it is not a cache: there is no warm-up, no hit
    # rate and nothing to restructure. It is a discount for not being in a hurry.
    #
    # WHAT IT COSTS IS THE CANDIDATE'S EXPERIENCE, WHICH IS WHY THE DEFAULT IS OFF. A batch
    # is answered on the provider's schedule — usually minutes, with a 24-hour ceiling —
    # rather than in the ~15s the split synchronous path takes today. Switching this on
    # changes what somebody sees after finishing an interview from "here is your report" to
    # "we are preparing your report", and AI-COST-MODEL.md is explicit that this is a
    # product decision rather than a refactor, worth costing properly before the price is
    # set, because it changes what the free tier can afford.
    #
    # So the path is complete, tested and one environment variable from live — and flipping
    # it is somebody's decision, not a default. Everything about the fallback holds either
    # way: a submission that fails runs synchronously in the same request, and a session
    # gets at most one batch attempt ever. See services/report/batch_job.py.
    REPORT_BATCH_ENABLED: bool = Field(
        default=False,
        description=(
            "Generate reports through the provider's batch API at half price, accepting "
            "minutes of latency instead of seconds. Only report_generation and "
            "report_analysis are ever eligible — nothing a candidate is waiting on can be "
            "batched, enforced by BATCHABLE_FEATURES in services/ai/batch.py. Ignored when "
            "the primary provider has no batch API."
        ),
    )
    REPORT_BATCH_MAX_WAIT_SECONDS: int = Field(
        default=15 * 60,
        ge=60,
        description=(
            "How long a submitted batch may run before the report gives up on it and is "
            "generated synchronously at full price instead.\n\n"
            "THIS IS A PATIENCE SETTING, NOT A TIMEOUT. Anthropic's own ceiling is 24 hours "
            "and most batches finish far inside an hour, so raising this collects more "
            "batches and saves more money. What bounds it is what somebody who has just "
            "finished an interview will tolerate before 'your report is being prepared' "
            "stops sounding like a system that works. Past it they are better served by a "
            "full-price report than by a cheaper one they have stopped waiting for.\n\n"
            "The batch is not cancelled when this expires — it may still complete and be "
            "collected later. The session simply stops being its audience."
        ),
    )
    #: Minutes before a report that used up its scoring retries may try again.
    #:
    #: THE RETRY CAP WAS A LIFETIME CAP, AND THAT IS WHY REPORTS STAYED "PENDING" FOREVER.
    #: After three failed scoring attempts `should_regenerate` returned False and the endpoint
    #: served the placeholder straight from the database with no model call — so "Generate
    #: again" did nothing, the report was permanently 0/100, and because an unscored report is
    #: deliberately never paywalled, the unlock could never appear either. Every interview that
    #: hit the earlier timeouts burned its three attempts and was then dead.
    #:
    #: The cap itself is right and stays: repeated page views must not fund an open-ended bill
    #: against a model that is failing. What was wrong was making it PERMANENT. A cap that
    #: resets after a cooling-off period still stops a reload storm — the expensive case, which
    #: happens in seconds — while letting a session recover once whatever broke has passed.
    #:
    #: 30 MINUTES, and the cost is bounded by arithmetic rather than by hope: a report is about
    #: $0.13, so a single session sitting on the retry button costs at most three attempts per
    #: half hour, and AI_DAILY_BUDGET_USD remains the backstop for everything. It also means
    #: every already-affected candidate recovers on their own, with nobody having to go and find
    #: them, which matters when a whole cohort was affected at once.
    #:
    #: Zero disables the cooldown and restores the old permanent cap. Do not.
    REPORT_UNSCORED_RETRY_COOLDOWN_MINUTES: float = 30.0
    #: Seconds resume analysis may spend on the AI before the upload is stored with whatever
    #: it managed to produce.
    #:
    #: REPORTED AS "in some cases the resume skills and projects are not been able to fetch"
    #: and "make sure that the resume uploading also works faster". Both symptoms came out of
    #: the same call, and the measurement is unambiguous. Three runs of `analyse_resume` over a
    #: realistic two-page resume (27 skills, 4 projects) against the live providers:
    #:
    #:      run 1  118.7s  27 skills,  1 project,  0 priority topics
    #:      run 2  214.5s  AIProviderUnavailableError — nothing at all
    #:      run 3  135.9s  21 skills,  0 projects,  0 priority topics
    #:
    #: EVERY attempt came back `stop_reason=max_tokens` / `finish_reason=length`. The single
    #: call asked for 20 skills and 6 projects in one JSON object under a 2600-token ceiling
    #: that the answer never once fit inside, so the JSON arrived cut off mid-array, the
    #: parser rejected it whole, and `generate_structured` re-ran it — twice per provider,
    #: across two providers, four truncated calls at ~$0.045 each. The endpoint's ceiling was
    #: hardcoded at 45s at the call site, so in production none of that was ever waited out:
    #: the upload sat for the full 45 seconds and then stored text_only. That is the "some
    #: cases" — a thin resume fits in 2600 tokens and works, a rich one can never fit and
    #: always fails.
    #:
    #: The call is now two concurrent halves (skills+experience, projects+focus) asking only
    #: for fields something actually reads, so the wall-clock is the larger half rather than
    #: the sum and neither half is anywhere near its ceiling. Measured after: ~10s for both.
    #:
    #: 35 SECONDS. Roughly 3x the measured wall-clock, which is headroom for a retry inside
    #: `generate_structured` on one half plus a slow afternoon — and still leaves the upload
    #: (storage write and DB insert, now overlapped with the analysis) far inside a managed
    #: host's ~100s gateway cut and the browser's 120s for this call (`useUploadResume`
    #: overrides the 30s default). Sitting inside the gateway matters more than it looks: a
    #: gateway 502 carries no CORS headers and reaches the browser as an opaque CORS error
    #: rather than as a timeout.
    #:
    #: Expiry is NOT a failure. `asyncio.wait` is used rather than `wait_for(gather(...))`, so
    #: whichever half finished is kept and stored; the extracted text is stored either way and
    #: still personalises the interview. Zero disables the budget, restoring the unbounded
    #: behaviour that made this a 3.5-minute request. Do not.
    RESUME_ANALYSIS_BUDGET_SECONDS: float = 35.0
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
    # services/tts/base.py and docs/AI-COST-MODEL.md. On Fish, now the default vendor below,
    # the same round costs roughly a tenth of that and lands under the round's own AI spend.
    # Either way the browser's speechSynthesis is free and already works; this is a paid
    # upgrade to how it sounds, so it stays something switched on deliberately by somebody
    # who has looked at the numbers. The vendor default only decides which bill you get once
    # you do — it does not turn anything on.
    TTS_ENABLED: bool = False
    TTS_PROVIDER: str = Field(
        default="fish",
        description=(
            "Which vendor: 'fish' or 'elevenlabs'. Both are fully supported and either "
            "value is a first-class choice — this default decides only which one a "
            "deployment gets when it says nothing.\n\n"
            "IT WAS 'elevenlabs' AND THE DEFAULT MOVED FOR TWO REASONS, ONE OF WHICH IS NOT "
            "MONEY. The money is real: ElevenLabs' Creator tier is ~$210 per million "
            "characters against Fish's ~$15 — see _USD_PER_CHAR in services/tts/fish.py and "
            "the tier table in services/tts/elevenlabs.py — which is roughly a fourteenth "
            "per character, and about a tenth per round once flash_v2_5's half-credit rate "
            "is taken into account. That is the difference between speech costing an order "
            "of magnitude more than every AI call in a GD round combined, and costing less "
            "than one of them.\n\n"
            "The other reason is fit. This product is Indian campus placement practice, and "
            "Fish's catalogue carries genuine Indian-English voices; a candidate rehearsing "
            "a Cognizant panel is better served by an interviewer who sounds like one they "
            "will actually meet than by a technically richer American one. ElevenLabs still "
            "wins on raw expressiveness, which is why it is kept intact and one env var "
            "away rather than removed.\n\n"
            "CHANGING THIS CHANGES THE VENDOR, NOT THE FEATURE. Voice ids in TTS_VOICE_IDS "
            "are account- and vendor-specific, so a deployment that switches provider must "
            "also swap that map — an ElevenLabs voice id sent to Fish is a 400, not a "
            "different-sounding voice. TTS_ENABLED still gates the whole thing, and is "
            "still False by default.\n\n"
            "Azure and Google Neural are the other cheap options with native en-IN voices. "
            "Add one as a new module in services/tts/ and a branch in factory.py; nothing "
            "else changes."
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
    TTS_USAGE_LEDGER_ENABLED: bool = Field(
        default=True,
        description=(
            "Record one row per synthesised utterance — vendor, model, speaker, "
            "characters, cost, and whether it came from the audio cache — so speech can "
            "appear in a margin figure at all.\n\n"
            "THIS IS NOT THE BUDGET GUARD. TTS_DAILY_BUDGET_USD is enforced from the Redis "
            "counter in services/tts/spend.py, which stays exactly as it is: a brake on the "
            "hot path that must not acquire a database dependency. This is the RECORD, and "
            "the two are separate because a per-UTC-day float with a 48h TTL and no "
            "attribution cannot answer 'what did speech cost us last month, per feature, "
            "per vendor' — which is the question /admin/revenue needs answered before it "
            "can report anything but gross.\n\n"
            "Writes are best-effort and can never fail a request. Set false to switch the "
            "ledger off without a deploy; the margin block then reports speech as "
            "unavailable rather than as zero."
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

    # ── Data protection contact (DPDP §8(9)–(10)) ─────────────────────────
    #
    # A NAMED HUMAN, NOT A ROLE MAILBOX. §8(9) asks for the contact of the person
    # who can answer questions about processing, and §8(10) for a grievance route.
    # "support@" satisfies neither: the statute is asking who is accountable.
    #
    # Empty by default, and empty is a VISIBLE state rather than a silent one — the
    # disclosure payload carries `configured: false`, the UI says the contact has
    # not been appointed yet, and a test asserts the app does not invent one. That
    # is deliberate: a made-up name in a compliance notice is worse than an obvious
    # gap, because it looks discharged.
    DPO_NAME: str = Field(
        default="",
        description="Name of the grievance officer / data-protection contact (DPDP §8(9))",
    )
    DPO_EMAIL: str = Field(
        default="",
        description="Mailbox that person actually reads (DPDP §8(10))",
    )
    GRIEVANCE_RESPONSE_DAYS: int = Field(
        default=30,
        description=(
            "Published SLA for answering a grievance. DPDP Rules propose 90 days as "
            "the outer limit for a Consent Manager; 30 is the ordinary commitment and "
            "is what the notice promises. Change the number here, not in the copy."
        ),
    )

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
