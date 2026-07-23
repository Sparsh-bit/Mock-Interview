"""
Code Execution Endpoints — api/v1/code.py

POST /api/v1/code/execute — compile & run a coding-round submission.

Execution is delegated to Piston (a sandboxed, free, no-key code runner).
We never execute candidate code in our own process. Only a fixed allowlist
of languages is accepted; everything else is rejected before any network call.
"""

from __future__ import annotations

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

# Allowlist: our language id -> (Piston language, pinned version).
# Versions are pinned to what /runtimes reports so behavior is reproducible.
_LANGUAGES: dict[str, tuple[str, str, str]] = {
    # id: (piston_language, version, source_filename)
    "java": ("java", "15.0.2", "Main.java"),
    "python": ("python", "3.10.0", "main.py"),
    "cpp": ("c++", "10.2.0", "main.cpp"),
    "sql": ("sqlite3", "3.36.0", "main.sql"),
}


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

    piston_lang, version, filename = _LANGUAGES[lang]
    payload = {
        "language": piston_lang,
        "version": version,
        "files": [{"name": filename, "content": request.source}],
        "stdin": request.stdin,
        # Guardrails so a runaway submission can't hang the request. Kept
        # within self-hosted Piston's default configured caps (compile 10s,
        # run 3s).
        "compile_timeout": 10_000,
        "run_timeout": 3_000,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{settings.PISTON_BASE_URL}/execute", json=payload)
    except httpx.RequestError as exc:
        logger.error("piston_network_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Code execution service is unavailable.") from exc

    if resp.status_code != 200:
        logger.error("piston_api_error", status=resp.status_code, body=resp.text[:300])
        raise HTTPException(status_code=502, detail="Code execution service returned an error.")

    data = resp.json()
    run = data.get("run", {}) or {}
    compile_stage = data.get("compile", {}) or {}

    # Surface a compile error (e.g. Java/C++) ahead of empty run output.
    stderr = compile_stage.get("stderr") or run.get("stderr") or ""
    stdout = run.get("stdout") or ""

    return CodeExecuteResponse(
        language=lang,
        stdout=stdout,
        stderr=stderr,
        exit_code=run.get("code"),
        timed_out=run.get("signal") == "SIGKILL",
        supported_languages=sorted(_LANGUAGES),
    )


@router.get("/languages")
async def list_languages(current_user: CurrentUser):  # noqa: ARG001
    """List supported coding-round languages."""
    return {"languages": sorted(_LANGUAGES)}
