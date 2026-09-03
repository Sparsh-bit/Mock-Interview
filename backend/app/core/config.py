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

import re
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REDACTED_VALUE = "[redacted]"

#: A field is redacted if any of these appears in its name. Substring, upper-cased,
#: and broader than it strictly needs to be.
#:
#: NOT `observability.PII_KEY_PARTS`, which was the obvious reuse and is wrong here:
#: that list is tuned for event payloads and matches none of `SUPABASE_SERVICE_KEY`
#: (it has "api_key" but not bare "key"), `SECRET_KEY` or `DATABASE_URL`. Checked,
#: not assumed — see tests/test_settings_redaction.py, which asserts every currently
#: secret-bearing field on this class is covered rather than trusting this list to
#: have been kept up to date.
_SECRET_NAME_PARTS: frozenset[str] = frozenset(
    {
        "SECRET",
        "KEY",  # bare, unlike the observability list: SUPABASE_SERVICE_KEY.
        "TOKEN",
        "PASSWORD",
        "PASSWD",
        "CREDENTIAL",
        "DSN",
        "SIGNATURE",
        "WEBHOOK",
        "SALT",
        "PRIVATE",
        "AUTH",
    }
)

#: `scheme://user:password@host`. DATABASE_URL and REDIS_URL carry a password and
#: match no name pattern — the credential is inside the value, not named by the key.
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][\w+.-]*://)(?P<user>[^:/@\s]+):[^@/\s]+@")


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(part in upper for part in _SECRET_NAME_PARTS)


def _redact_url_credentials(value: str) -> str:
    """Blank the password inside a URL, keeping scheme, user and host.

    Those three are what makes the repr useful — which database, as whom — and the
    password is the only part that is a credential.
    """
    return _URL_CREDENTIALS.sub(rf"\g<scheme>\g<user>:{REDACTED_VALUE}@", value)


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
    #: Origins the browser is allowed to call this API from.
    #:
    #: `NoDecode` IS LOAD-BEARING AND THE REASON THIS FIELD LOOKS UNUSUAL. A `list[str]` is a
    #: COMPLEX field, so pydantic-settings JSON-decodes it inside
    #: `EnvSettingsSource.prepare_field_value` — before any validator here runs, and before
    #: main.py has configured structlog. A value that is not clean JSON therefore did not
    #: produce a validation message; it produced this, at import:
    #:
    #:     json.decoder.JSONDecodeError: Expecting value: line 1 column 2 (char 1)
    #:     SettingsError: error parsing value for field "CORS_ORIGINS" from source
    #:       "EnvSettingsSource"
    #:
    #: The container then exits instantly with a raw traceback and NO structured logging, the
    #: platform reports the deployment unhealthy, its edge answers 502, and the browser reports
    #: every request as "blocked by CORS policy: No Access-Control-Allow-Origin" — because a
    #: 502 page carries no CORS headers. Four symptoms, none of them adjacent to a malformed
    #: environment variable.
    #:
    #: MEASURED IN A CONTAINER: of the four shapes a person plausibly pastes, one booted.
    #: `["https://a"]` worked; backslash-escaped JSON, JSON copied with its surrounding quotes,
    #: and a comma-separated list all crashed the process.
    #:
    #: NoDecode turns the decoding off at the source so the validator below owns it, which is
    #: the only layer that can fail by name.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> object:
        """
        Accept the shapes people actually paste, and refuse the rest BY NAME.

        WHY TOLERANCE RATHER THAN STRICTNESS. Every shape handled here is unambiguous about
        intent — they all mean "these origins". Refusing them bought no safety; it only moved
        the failure to the worst possible place, a production boot with no diagnosis.
        Deployment dashboards and CLIs render values escaped, runbooks carry shell quoting, and
        a comma-separated list is the obvious guess. All three used to be fatal.

        WHAT IS DELIBERATELY NOT TOLERATED. Nothing here widens what is ALLOWED. There is no
        wildcard fallback and no "on error, allow everything" — that would convert a loud crash
        into a silent security hole, which is strictly worse than the bug being fixed. A value
        that genuinely cannot be read still raises, and `allow_credentials` is only ever paired
        with an explicit list. Blank entries are dropped rather than kept, because an empty
        string in an allowlist matches nothing while looking like an entry.
        """
        if v is None:
            return []
        if isinstance(v, (list, tuple)):
            return [str(x).strip() for x in v if str(x).strip()]
        if not isinstance(v, str):
            return v

        text = v.strip()
        if not text:
            return []

        # Peel one layer of wrapping quotes, then un-escape \" — the two ways a JSON array
        # arrives mangled by a dashboard, a CLI, or a shell.
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1].strip()
        if '\\"' in text:
            text = text.replace('\\"', '"')

        if text.startswith("["):
            import json  # noqa: PLC0415 - only needed on this path

            try:
                parsed = json.loads(text)
            except ValueError as exc:
                raise ValueError(
                    f"CORS_ORIGINS looks like a JSON array but could not be parsed: {exc}. "
                    'Accepted forms: ["https://a","https://b"] (JSON) or '
                    "https://a,https://b (comma-separated)."
                ) from exc
            if not isinstance(parsed, list):
                raise ValueError(
                    "CORS_ORIGINS parsed to "
                    f"{type(parsed).__name__}, not a list. Accepted forms: "
                    '["https://a","https://b"] (JSON) or https://a,https://b (comma-separated).'
                )
            return [str(x).strip() for x in parsed if str(x).strip()]

        if text.startswith("{"):
            raise ValueError(
                "CORS_ORIGINS is a list of origins, not an object. Accepted forms: "
                '["https://a","https://b"] (JSON) or https://a,https://b (comma-separated).'
            )

        # A bare origin, or several separated by commas.
        return [part.strip() for part in text.split(",") if part.strip()]
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
    #: A SEPARATE connection for schema changes, because migrations and request traffic want
    #: opposite things from a pooler.
    #:
    #: THE OUTAGE THIS EXISTS TO PREVENT. Alembic's correctness rests on one guarantee: a
    #: revision either fully applies — its DDL *and* its `alembic_version` update — or not at
    #: all. That guarantee is transactional, and a TRANSACTION-MODE pooler cannot provide it:
    #: each statement may be handed a different backend, so DDL can commit while the version
    #: update lands somewhere that never commits. The schema then sits AHEAD of the stamp, and
    #: the next `upgrade head` re-runs a revision whose table already exists:
    #:
    #:     asyncpg.exceptions.DuplicateTableError: relation "report_jobs" already exists
    #:
    #: boot.py treats a failed migration as fatal and the container runs `boot.py && uvicorn`,
    #: so the `&&` short-circuits and the server never starts. Every path answers 502, the
    #: browser calls it a CORS error because a 502 page carries no CORS headers, and — because
    #: the condition is deterministic — it never self-heals.
    #:
    #: SO: the app keeps the transaction pooler (port 6543), which is what lets 200 candidates
    #: share 15 Postgres backends, and schema changes get a SESSION-mode connection (port 5432
    #: on the same Supabase host) where a transaction means what Alembic thinks it means. This
    #: also restores db/boot_lock.py's session-scoped advisory lock for free.
    #:
    #: EMPTY MEANS "USE DATABASE_URL", so a deployment against a direct Postgres — local dev,
    #: or any host without a pooler — needs no second variable and behaves exactly as before.
    MIGRATION_DATABASE_URL: str = ""

    @property
    def migration_database_url(self) -> str:
        """The URL schema changes should use: MIGRATION_DATABASE_URL, else DATABASE_URL."""
        raw = (self.MIGRATION_DATABASE_URL or "").strip() or self.DATABASE_URL
        # Same driver normalisation the DATABASE_URL validator applies, so the two cannot
        # disagree about which driver they mean.
        for prefix in ("postgresql://", "postgres://"):
            if raw.startswith(prefix):
                return raw.replace(prefix, "postgresql+asyncpg://", 1)
        return raw

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

    #: The pooler's "Connection pool size" — connections it opens to ACTUAL POSTGRES, shared
    #: across every client. NOT the same number as DB_CONNECTION_CEILING above, and the
    #: difference is the one that matters:
    #:
    #:   DB_CONNECTION_CEILING   "Max client connections" — how many clients may connect TO
    #:                           the pooler. 200 on Supabase Nano, and fixed there.
    #:   DB_POOLER_POOL_SIZE     "Connection pool size" — how many Postgres backends the
    #:                           pooler holds for all of them together. 15 on Nano by default,
    #:                           and editable.
    #:
    #: WHY THIS IS THE TIGHTEST CEILING IN THE WHOLE SYSTEM. In transaction mode an IDLE
    #: application connection costs zero Postgres backends — but one holding an OPEN
    #: TRANSACTION occupies one of these for as long as it stays open. So the limit on real
    #: concurrency is neither the app's pool (DB_POOL_SIZE + DB_MAX_OVERFLOW) nor the client
    #: limit; it is this number of simultaneous open transactions. Past it, requests queue
    #: INSIDE THE POOLER, where nothing in this process can see or log them.
    #:
    #: AND IT DOES NOT SCALE WITH WORKERS OR REPLICAS. Every other budget in this file is per
    #: process and gets multiplied by PROCESS_COUNT. This one is a property of the database:
    #: four workers share the same 15. Adding compute cannot relieve it — only raising the
    #: pool size (bounded by Postgres's own max_connections) or holding transactions for less
    #: time can.
    #:
    #: NO DEFAULT, for the same reason as the two ceilings above: it varies by compute size
    #: and a guessed value is a check that is confidently wrong. 0 means "not configured".
    #: Read it off Supabase → Settings → Database → Connection pooling.
    DB_POOLER_POOL_SIZE: int = 0

    # ── Deployment topology ───────────────────────────────────────────────
    #: How many copies of this process the platform runs. NOT read by the app to
    #: change behaviour — it is read by the startup audits that multiply a per-process
    #: budget by it, because every connection ceiling in this file is a PER-FLEET
    #: number that the code can only see one Nth of. Keep it equal to the replica
    #: count in render.yaml; a stale value here makes the audits silently wrong in
    #: the optimistic direction.
    WEB_REPLICA_COUNT: int = 1

    #: Uvicorn worker processes INSIDE each replica.
    #:
    #: THE NAME IS NOT OURS AND THAT IS THE WHOLE POINT. Uvicorn already defaults
    #: `--workers` to `$WEB_CONCURRENCY`, so setting this env var is what actually starts the
    #: extra processes — no Dockerfile flag, no start command to keep in step. Declaring it
    #: here means the application reads the SAME variable the server obeys, so the two cannot
    #: disagree. A second knob of our own invention could.
    #:
    #: WHY IT HAD TO BE DECLARED AT ALL. Every connection ceiling in this file is per PROCESS,
    #: and until now the audits multiplied by WEB_REPLICA_COUNT alone — which was correct only
    #: because there was exactly one worker. Four workers on one replica is four pools, four
    #: Redis pools and four report semaphores, and the audits would have reported one quarter
    #: of the truth while saying nothing was wrong. That is the failure mode this file keeps
    #: warning about, so it gets closed here rather than documented.
    #:
    #: ONE WORKER IS THE RIGHT DEFAULT. A worker is bounded by a core, so more than one buys
    #: nothing on a fraction of a CPU (Render's free plan is 0.1 vCPU) and costs a full set of
    #: per-process budgets. Raise it with the CPU allocation, never ahead of it.
    WEB_CONCURRENCY: int = 1

    @property
    def PROCESS_COUNT(self) -> int:  # noqa: N802 - matches the settings naming convention
        """
        How many copies of this process exist across the whole deployment.

        THE NUMBER EVERY PER-PROCESS BUDGET MUST BE MULTIPLIED BY, and the only one. A pool
        belongs to a process, not to a container: `numReplicas: 2` with `WEB_CONCURRENCY=4`
        is eight pools, eight Redis pools and eight report semaphores. Anything auditing a
        fleet-wide ceiling reads this instead of either factor on its own — the two audits in
        db/session.py and db/redis.py do, and test_process_count.py holds them to it.
        """
        return self.WEB_REPLICA_COUNT * self.WEB_CONCURRENCY

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
    GROQ_DAILY_REQUEST_LIMIT: int = Field(
        # 1,000 BECAUSE THAT IS WHAT GROQ_MODEL'S DEFAULT ALLOWS. This was 2,000 - twice the
        # ceiling it was capping - so the cap could never fire, and the rung kept calling until
        # Groq answered 429. That is exactly the outcome the note below describes as the reason
        # this field exists, and a cap that cannot fire is worse than no cap because it reads as
        # protection. The rung is only reached during an outage, when nobody is reading two
        # field descriptions to notice the defaults disagree.
        default=1000,
        description=(
            "Requests a day the free-tier burst rung may make before it is dropped from the "
            "provider chain. 0 disables the cap. "
            "COUNTED IN REQUESTS BECAUSE THE FREE TIER IS: a Groq call costs $0.00, so "
            "AI_DAILY_BUDGET_USD never moves and is structurally blind to it. Past the "
            "ceiling Groq answers 429 — nothing breaks, because the rung is only reached "
            "once the paid providers have already failed, but it fails after a round trip "
            "and leaves the account rate-limited, which the next health check reports as a "
            "provider outage. "
            "NOTE: services/ai/burst_rung.py records 1,000/day for openai/gpt-oss-20b, "
            "verified 2026-08-30. The limits are per-model and they change — set this to "
            "what your plan actually allows for the model in GROQ_MODEL."
        ),
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

    #: Account provisioning, per calling address, per minute.
    #:
    #: 5, against a general read budget of 120. A real person triggers this ONCE per
    #: sign-up and once per login, so five a minute is invisible to them and is two orders
    #: of magnitude below what a script wants. It has to stay strictly below
    #: RATE_LIMIT_READ_PER_MINUTE or it can never trip first, which is asserted by
    #: tests/test_auth_rate_limit.py rather than left to whoever edits this next.
    RATE_LIMIT_AUTH_PER_MINUTE: int = 5

    #: The same, per hour. A per-minute limit on its own is beaten by waiting; this is what
    #: makes the total cost of minting accounts from one place bounded rather than paced.
    #:
    #: 40 is deliberately generous for a shared address — a campus lab or a college NAT can
    #: put a whole cohort behind one IP on results day, and locking that cohort out is a
    #: worse outcome than the abuse. Revisit if a real campus ever trips it.
    RATE_LIMIT_AUTH_PER_HOUR: int = 40

    #: Unauthenticated reads of a shared report, per calling address, per minute.
    RATE_LIMIT_PUBLIC_PER_MINUTE: int = 30

    #: Where this deployment's data actually sits, as a human-readable region.
    #:
    #: EMPTY BY DEFAULT AND THAT IS DELIBERATE. `docs/DATA-RESIDENCY.md` records that the
    #: region could not be established from this repository — `render.yaml` declares
    #: `singapore` and marks itself unconfirmed, and DNS proves nothing. Defaulting this to
    #: a country would make every deployment CLAIM a residency nobody checked, which is the
    #: failure mode CLAUDE.md records for the stale trial-allowance note: a plausible
    #: fabrication is worse than an obvious gap, because it looks like the question was
    #: answered.
    #:
    #: Unset, `/privacy` says the region has not been confirmed. Set, it names it. This is
    #: the same derived-from-configuration mechanism `services/legal/disclosure.py` uses for
    #: processors, and for the same reason: a notice naming the wrong country is worse than
    #: no notice, because it is a statement the candidate relied on.
    #:
    #: Set it to what the Supabase dashboard actually says, e.g. "Singapore (ap-southeast-1)".
    DATA_REGION: str = ""

    #: The header a TRUSTED proxy writes the caller's address into, or "" to read none.
    #:
    #: EMPTY BY DEFAULT AND THAT IS THE SAFE SETTING. A header is only worth reading when
    #: something we operate is known to overwrite it; unset, `core/client_ip.py` ignores
    #: every header and uses the peer address. Set it to `cf-connecting-ip` behind
    #: Cloudflare, or `x-forwarded-for` behind a platform load balancer.
    TRUSTED_PROXY_HEADER: str = ""

    #: How many proxies of our own sit in front, when TRUSTED_PROXY_HEADER is
    #: `x-forwarded-for`. Counted from the RIGHT-hand end of the list, because that header
    #: is append-only: a caller controls its left and our infrastructure writes its right.
    TRUSTED_PROXY_HOPS: int = 1

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
    #: Judge0 requests a day the whole deployment may make, across every process.
    #:
    #: COUNTED IN REQUESTS, BECAUSE THE FREE TIER IS. A Judge0 CE call costs $0.00, so
    #: AI_DAILY_BUDGET_USD never moves and cannot see this at all — the same blindness that
    #: GROQ_DAILY_REQUEST_LIMIT exists for.
    #:
    #: WHY A FLEET LIMIT WHEN THERE IS ALREADY A RATE LIMIT. RATE_LIMIT_CODE_EXEC_PER_MINUTE
    #: is keyed PER USER, so it caps one candidate at 20 a minute and says nothing whatsoever
    #: about two hundred of them. The default CODE_EXEC_PROVIDER is the PUBLIC Judge0 CE
    #: instance, which is free and shared with the entire internet; a campus drive pointed at
    #: it is a load nobody agreed to, and it ends in 429s and a blocked egress IP for the
    #: whole deployment rather than a polite slowdown.
    #:
    #: 0 DISABLES IT, AND THAT IS THE DEFAULT. Judge0 CE publishes no per-IP number, and this
    #: file's own rule for provider ceilings is that a guessed one is a check that is
    #: confidently wrong (see DB_CONNECTION_CEILING). Set it for a drive — docs/RAILWAY.md
    #: has the arithmetic — and leave it off for ordinary traffic.
    #:
    #: IGNORED WHEN JUDGE0_API_KEY IS SET. The guard protects a free shared service; with a
    #: RapidAPI key the capacity has been bought, and throttling it would make the guard the
    #: cause of the outage it exists to prevent.
    JUDGE0_DAILY_REQUEST_LIMIT: int = 0

    JUDGE0_API_KEY: str = Field(
        default="",
        description="Optional RapidAPI key. Empty = use the free public CE instance.",
    )

    # ── Sentry (error tracking, optional) ─────────────────────────────────
    SENTRY_DSN: str = Field(default="", description="Sentry DSN for error tracking")

    # ── The operator (DPDP §5, and the e-commerce display duty) ───────────
    #
    # WHO "WE" IS. Every policy in the product speaks in the first person - "we
    # will refund you", "we do not promise" - and until this existed, nothing said
    # who that was. Three obligations land on the same fact:
    #
    #   * DPDP's §5 notice is given BY a Data Fiduciary, and a notice that does not
    #     say which one tells the Data Principal nothing they can act on. The whole
    #     disclosure payload below is that notice; this is the party issuing it.
    #   * The Consumer Protection (E-Commerce) Rules 2020 require an e-commerce
    #     entity to display its legal name.
    #   * A gateway's merchant terms assume the merchant is identifiable to the payer.
    #
    # UNLIKE `DPO_NAME`, THIS HAS A DEFAULT, and the difference is the point. An
    # unset grievance officer is left visibly empty because inventing a named human
    # would look like the duty was discharged. The operator is not unknown - it is
    # the company shipping the software - so defaulting it is honest, and leaving it
    # blank would only produce a notice issued by nobody.
    #
    # This is the operator's LEGAL NAME, not the product's. `APP_NAME` above is the
    # product. Collapsing the two would satisfy a "the operator is named" check while
    # identifying nobody. The frontend mirror is `BRAND.company` in lib/brand.ts.
    OPERATOR_LEGAL_NAME: str = Field(
        default="Concilio Solutions",
        description=(
            "Legal name of the entity operating the service - the Data Fiduciary "
            "under DPDP and the merchant of record. Not the product name."
        ),
    )

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

    # ── What this object is allowed to say about itself ───────────────────

    def __repr__(self) -> str:
        """
        Pydantic's generated repr prints every field value. On this machine that is
        the Supabase JWT secret (88 chars, signs every auth token), the service key
        (219 chars, bypasses Row Level Security entirely), both model-provider keys
        and the database password — 4.5 KB of it, in one string.

        THAT STRING REACHES CI LOGS WITHOUT ANYBODY WRITING IT OUT. pytest prints the
        repr of every local in a failing frame, so one assertion touching `settings`
        publishes the lot to a build log; so does a logged exception, a Sentry event
        that got past the scrubber, a debugger, or a stray print in a script.

        Fixed HERE and not in a pytest hook on purpose: a conftest hook covers pytest
        and nothing else, and the same object is repr'd by all four of those paths.

        The redaction is by field NAME, and deliberately broad — over-redacting a repr
        costs nothing, under-redacting costs every credential. It is not
        `SecretStr`, which would be the idiomatic answer but changes the type at ~200
        call sites, and not `Field(repr=False)`, which hides that the field exists at
        all and has to be remembered for each new field.
        """
        parts = []
        for name, value in self:
            if isinstance(value, str) and value and _is_secret_name(name):
                parts.append(f"{name}={REDACTED_VALUE!r}")
            elif isinstance(value, str) and value:
                parts.append(f"{name}={_redact_url_credentials(value)!r}")
            else:
                # Non-strings and empty strings: a bool, an int, a list of CORS
                # origins. None of these has ever been a credential, and blanking
                # them would make the repr useless for the thing it is for.
                parts.append(f"{name}={value!r}")
        return f"{type(self).__name__}({', '.join(parts)})"

    # `str()` does not fall back to `__repr__` when the class defines `__str__`,
    # and pydantic's BaseModel defines one. Without this, `f"{settings}"` prints
    # everything the line above just removed.
    __str__ = __repr__

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

    THE `except` IS THE SECOND HALF OF THE REDACTION ABOVE, and it guards a leak
    `__repr__` cannot reach. When a required variable is missing, pydantic raises a
    ValidationError whose every error carries `input_value` — and for a BaseSettings
    that input is THE WHOLE ENVIRONMENT-DERIVED DICT, every other secret included.
    Nobody writes that repr; pydantic does, and pytest prints it on any test that
    constructs Settings, into CI logs that are readable by anyone who can read the
    build.

    Re-raised carrying the field NAMES and the reason, which is the entire useful
    content of the original — "SUPABASE_ANON_KEY: Field required" tells you what to
    set. `from None` because chaining would print the original, which is the thing
    being suppressed.
    """
    try:
        return Settings()
    except ValidationError as exc:  # pragma: no cover - exercised in tests
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<model>'}: {err['msg']}"
            for err in exc.errors()
        )
        raise RuntimeError(
            f"Settings failed to load ({exc.error_count()} problem(s)): {problems}. "
            "Values are omitted deliberately — see core/config.py."
        ) from None


# Module-level alias for ergonomic imports:
#   from app.core.config import settings
settings: Settings = get_settings()
