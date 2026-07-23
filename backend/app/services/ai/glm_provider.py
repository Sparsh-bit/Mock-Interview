"""
GLM Provider — glm_provider.py

ZhipuAI GLM implementation of BaseAIProvider.
Supports GLM-4 series models with native JSON mode.

API documentation: https://open.bigmodel.cn/dev/api/normal-model/glm-4

Configuration:
    AI_PROVIDER=glm
    GLM_API_KEY=<your-zhipuai-key>
    GLM_MODEL=glm-4-flash   # or glm-4, glm-4-air, glm-4-long
"""

from __future__ import annotations

import httpx
import structlog

from .base_provider import BaseAIProvider, ProviderError, ProviderRequest, ProviderResponse

logger = structlog.get_logger(__name__)

from app.core.config import settings

_CHAT_COMPLETIONS_PATH = "/chat/completions"


class GLMProvider(BaseAIProvider):
    """
    ZhipuAI GLM provider.

    Uses httpx.AsyncClient for connection pooling and proper timeout control.
    All exceptions from httpx are caught and re-raised as ProviderError so
    the rest of the application only needs to handle one error type.
    """

    def __init__(self, api_key: str, model: str = "glm-4-flash") -> None:
        if not api_key:
            raise ValueError("GLMProvider requires a non-empty api_key.")
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=settings.GLM_BASE_URL,
            # Conservative timeouts: connect fast, allow long reads for streaming
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=5.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    # ─── BaseAIProvider interface ─────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "glm"

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        model = request.model_override or self._model

        payload: dict = {
            "model": model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        # GLM supports JSON mode via response_format
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}

        log = logger.bind(
            provider="glm",
            model=model,
            message_count=len(request.messages),
            json_mode=request.json_mode,
            max_tokens=request.max_tokens,
        )
        log.debug("glm_request_start")

        try:
            response = await self._client.post(_CHAT_COMPLETIONS_PATH, json=payload)
        except httpx.TimeoutException as exc:
            log.error("glm_timeout", error=str(exc))
            raise ProviderError(
                f"GLM request timed out after {exc}",
                provider=self.provider_name,
            ) from exc
        except httpx.RequestError as exc:
            log.error("glm_network_error", error=str(exc))
            raise ProviderError(
                f"GLM network error: {exc}",
                provider=self.provider_name,
            ) from exc

        if response.status_code != 200:
            error_body = response.text[:500]
            log.error(
                "glm_api_error",
                status_code=response.status_code,
                body=error_body,
            )
            raise ProviderError(
                f"GLM API returned {response.status_code}: {error_body}",
                provider=self.provider_name,
                status_code=response.status_code,
                raw_error=error_body,
            )

        data = response.json()

        try:
            choice = data["choices"][0]
            usage = data.get("usage", {})
        except (KeyError, IndexError) as exc:
            raise ProviderError(
                f"Unexpected GLM response shape: {str(data)[:200]}",
                provider=self.provider_name,
                raw_error=data,
            ) from exc

        result = ProviderResponse(
            content=choice["message"]["content"],
            model=data.get("model", model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason", "stop"),
        )

        log.debug(
            "glm_request_complete",
            finish_reason=result.finish_reason,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )

        return result

    async def health_check(self) -> bool:
        """
        Sends a minimal completion to verify connectivity and API key validity.
        Returns False on any failure — never raises.
        """
        try:
            await self.complete(
                ProviderRequest(
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    temperature=0.0,
                )
            )
            return True
        except Exception:
            logger.exception("glm_health_check_failed")
            return False

    async def close(self) -> None:
        await self._client.aclose()
