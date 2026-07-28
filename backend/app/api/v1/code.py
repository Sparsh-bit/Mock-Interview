"""
Code Execution Endpoints — api/v1/code.py

POST /api/v1/code/execute — compile & run a coding-round submission.

Execution is delegated to an external sandbox — we never run candidate code in
our own process. Only a fixed allowlist of languages is accepted; anything else
is rejected before a network call is made.

Two runners are supported, selected by CODE_EXEC_PROVIDER:

  judge0 (default)  Judge0 CE — free, no API key, works on hosts that cannot run
                    privileged containers (Render free tier included).
  piston            Self-hosted Piston via docker-compose, for local dev.
                    NOTE: Piston's *public* API (emkc.org) went whitelist-only
                    on 2026-02-15 and now answers 401, so it can only be used
                    self-hosted. Pointing production at it is what broke this
                    endpoint previously.

This endpoint never returns 5xx for a runner problem. A failed run comes back as
a normal 200 with the reason in `stderr`, because a 5xx here surfaces in the
browser console as an opaque network/CORS error instead of something the
candidate can act on.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys

logger = structlog.get_logger(__name__)
router = APIRouter()

#: Keep the AI review inside the host gateway timeout so a slow model degrades
#: to an honest "unavailable" instead of a CORS-header-less 502.
_ANALYSE_AI_BUDGET_SECONDS = 45.0

# Allowlist: our language id -> (Piston language, pinned version, filename).
# Versions are pinned to what Piston's /runtimes reports so behavior is
# reproducible across self-hosted deployments.
_LANGUAGES: dict[str, tuple[str, str, str]] = {
    # id: (piston_language, version, source_filename)
    "java": ("java", "15.0.2", "Main.java"),
    "python": ("python", "3.10.0", "main.py"),
    "cpp": ("c++", "10.2.0", "main.cpp"),
    "sql": ("sqlite3", "3.36.0", "main.sql"),
}

# Judge0 numeric language ids, verified against ce.judge0.com/languages.
# Java 17 matters most here — the product is Java-FSE focused.
_JUDGE0_LANGUAGE_IDS: dict[str, int] = {
    "java": 91,    # Java (JDK 17.0.6)
    "python": 92,  # Python (3.11.2)
    "cpp": 54,     # C++ (GCC 9.2.0)
    "sql": 82,     # SQL (SQLite 3.27.2)
}

#: Judge0 status ids that mean the program was killed for exceeding its limits.
_JUDGE0_TIMEOUT_STATUS = 5


class CodeExecuteRequest(BaseModel):
    language: str = Field(description="One of: java | python | cpp | sql")
    source: str = Field(min_length=1, max_length=50_000)
    stdin: str = Field(default="", max_length=10_000)


class CodeExecuteResponse(BaseModel):
    language: str
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool = False
    supported_languages: list[str]


_code_exec_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_CODE_EXEC_PER_MINUTE,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_ai(user_id) + ":code",
    action="running code",
)


@router.post("/execute", response_model=CodeExecuteResponse, dependencies=[Depends(_code_exec_rate_limit)])
async def execute_code(
    request: CodeExecuteRequest,
    current_user: CurrentUser,  # noqa: ARG001 — auth required; user identity not otherwise needed
):
    from fastapi import HTTPException  # noqa: PLC0415

    lang = request.language.lower().strip()
    if lang not in _LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{request.language}'. Supported: {sorted(_LANGUAGES)}",
        )

    provider = settings.CODE_EXEC_PROVIDER.lower().strip()
    try:
        if provider == "piston":
            stdout, stderr, exit_code, timed_out = await _run_on_piston(lang, request)
        else:
            stdout, stderr, exit_code, timed_out = await _run_on_judge0(lang, request)
    except _RunnerUnavailable as exc:
        # Deliberately a 200: a 5xx here shows up in the browser console as an
        # opaque network/CORS failure, which tells the candidate nothing. Put
        # the reason where they will actually read it.
        logger.error("code_exec_unavailable", provider=provider, error=str(exc))
        return CodeExecuteResponse(
            language=lang,
            stdout="",
            stderr=f"Could not reach the code execution service ({provider}). {exc}",
            exit_code=None,
            supported_languages=sorted(_LANGUAGES),
        )

    return CodeExecuteResponse(
        language=lang,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        timed_out=timed_out,
        supported_languages=sorted(_LANGUAGES),
    )


class _RunnerUnavailable(RuntimeError):
    """The external sandbox could not be reached or refused the request."""


async def _run_on_judge0(
    lang: str, request: CodeExecuteRequest
) -> tuple[str, str, int | None, bool]:
    """
    Execute on Judge0 CE. `wait=true` makes this a single synchronous call, so
    there is no token to poll.
    """
    headers = {"Content-Type": "application/json"}
    if settings.JUDGE0_API_KEY:
        # RapidAPI-hosted Judge0 needs these; the public CE instance ignores them.
        headers["X-RapidAPI-Key"] = settings.JUDGE0_API_KEY
        headers["X-RapidAPI-Host"] = settings.JUDGE0_BASE_URL.replace("https://", "")

    payload = {
        "language_id": _JUDGE0_LANGUAGE_IDS[lang],
        "source_code": request.source,
        "stdin": request.stdin,
        # Guardrails so a runaway submission can't hang the request.
        "cpu_time_limit": 5,
        "wall_time_limit": 10,
    }

    url = f"{settings.JUDGE0_BASE_URL.rstrip('/')}/submissions?base64_encoded=false&wait=true"
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        raise _RunnerUnavailable(str(exc)) from exc

    if resp.status_code not in (200, 201):
        raise _RunnerUnavailable(f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    status = (data.get("status") or {}).get("id")
    # Compile errors arrive in compile_output, not stderr — surface them first
    # or a Java candidate sees an empty box.
    stderr = data.get("compile_output") or data.get("stderr") or ""
    if not stderr and data.get("message"):
        stderr = data["message"]

    return (
        data.get("stdout") or "",
        stderr,
        data.get("exit_code"),
        status == _JUDGE0_TIMEOUT_STATUS,
    )


async def _run_on_piston(
    lang: str, request: CodeExecuteRequest
) -> tuple[str, str, int | None, bool]:
    """Execute on a SELF-HOSTED Piston instance (docker-compose, local dev)."""
    piston_lang, version, filename = _LANGUAGES[lang]
    payload = {
        "language": piston_lang,
        "version": version,
        "files": [{"name": filename, "content": request.source}],
        "stdin": request.stdin,
        # Within self-hosted Piston's default caps (compile 10s, run 3s).
        "compile_timeout": 10_000,
        "run_timeout": 3_000,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{settings.PISTON_BASE_URL}/execute", json=payload)
    except httpx.RequestError as exc:
        raise _RunnerUnavailable(str(exc)) from exc

    if resp.status_code != 200:
        raise _RunnerUnavailable(f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    run = data.get("run", {}) or {}
    compile_stage = data.get("compile", {}) or {}

    return (
        run.get("stdout") or "",
        compile_stage.get("stderr") or run.get("stderr") or "",
        run.get("code"),
        run.get("signal") == "SIGKILL",
    )


@router.get("/languages")
async def list_languages(current_user: CurrentUser):  # noqa: ARG001
    """List supported coding-round languages."""
    return {"languages": sorted(_LANGUAGES)}


# ─── AI code review ───────────────────────────────────────────────────────────


class CodeAnalyseRequest(BaseModel):
    language: str
    source: str = Field(min_length=1, max_length=50_000)
    problem_title: str = Field(default="Coding question", max_length=300)
    problem_description: str = Field(default="", max_length=4_000)
    difficulty: str = Field(default="medium", max_length=20)
    #: Output from the last run, when the candidate ran it before submitting.
    #: Evidence for the reviewer, not a verdict on its own.
    stdout: str = Field(default="", max_length=4_000)
    stderr: str = Field(default="", max_length=4_000)


@router.post("/analyse", dependencies=[Depends(_code_exec_rate_limit)])
async def analyse_code(request: CodeAnalyseRequest, current_user: CurrentUser):
    """
    Review a coding submission the way an interviewer would: graded correctness
    (correct / nearly / partially / incorrect), what approach was taken and
    whether a brute-force solution is sound, plus a soft flag when the code
    looks AI-authored.

    Never 5xx on an AI failure — the candidate gets an honest "not available"
    payload instead of a console error.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import CodingEvaluation  # noqa: PLC0415

    lang = request.language.lower().strip()
    if lang not in _LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{request.language}'. Supported: {sorted(_LANGUAGES)}",
        )

    builder = PromptBuilder(get_prompt_loader())
    messages = builder.chat(
        system_template="coding_evaluator",
        user_content=f"Review this {lang} submission:\n\n```{lang}\n{request.source}\n```",
        language=lang,
        problem_title=request.problem_title,
        problem_description=request.problem_description or "(not provided — infer it from the code)",
        difficulty=request.difficulty,
        stdout=request.stdout.strip() or "(not run)",
        stderr=request.stderr.strip() or "(none)",
    )

    try:
        evaluation, _ = await asyncio.wait_for(
            generate_structured(
                CodingEvaluation,
                messages,
                max_tokens=1600,
                attempts_per_provider=1,
                cost_tier=CostTier.BALANCED,
                context="code_analysis",
            ),
            timeout=_ANALYSE_AI_BUDGET_SECONDS,
        )
    except (AIProviderUnavailableError, TimeoutError):
        logger.warning("code_analysis_unavailable", language=lang)
        return {"available": False, "evaluation": None}

    return {"available": True, "evaluation": evaluation.model_dump()}
