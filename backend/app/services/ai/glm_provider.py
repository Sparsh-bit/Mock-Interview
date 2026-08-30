"""
OpenAI-compatible chat-completion provider — glm_provider.py

A single implementation shared by every provider that speaks the standard
`POST /chat/completions` shape (ZhipuAI/GLM, NVIDIA NIM, and by extension
OpenAI itself). Only base_url/api_key/model/provider_name differ between
them -- see provider_factory.py for how each is constructed from settings.

Configuration:
    AI_PROVIDER=glm
    GLM_API_KEY=<your-zhipuai-key>
    GLM_MODEL=glm-4-flash            # or glm-4, glm-4-air, glm-5.2, ...
    GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4

    AI_PROVIDER=nvidia
    NVIDIA_API_KEY=<your-nvidia-nim-key>
    NVIDIA_MODEL=nvidia/nemotron-3-ultra-550b-a55b
    NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import structlog

from .base_provider import (
    BaseAIProvider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    StreamChunk,
)

logger = structlog.get_logger(__name__)

_CHAT_COMPLETIONS_PATH = "/chat/completions"


class OpenAICompatibleProvider(BaseAIProvider):
    """
    Generic provider for any OpenAI-compatible `/chat/completions` API.

    Uses httpx.AsyncClient for connection pooling and proper timeout control.
    All exceptions from httpx are caught and re-raised as ProviderError so
    the rest of the application only needs to handle one error type.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        provider_name: str,
        read_timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError(f"{provider_name} provider requires a non-empty api_key.")
        self._api_key = api_key
        self._model = model
        self._provider_name = provider_name
        self._client = httpx.AsyncClient(
            base_url=base_url,
            # Conservative timeouts: connect fast, allow long reads for
            # heavier/reasoning models that can take significantly longer.
            timeout=httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=5.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    # ─── BaseAIProvider interface ─────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def supports_streaming(self) -> bool:
        return True

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        """
        The answer as text deltas, over the OpenAI-compatible SSE protocol.

        `"stream": true` turns the response into `data: {json}` lines terminated by
        `data: [DONE]`. Everything else about the request is identical to `complete`, so a
        streamed call and a whole one differ only in when the bytes arrive.

        JSON MODE STILL APPLIES. The model is still told to answer with a JSON object; the
        difference is that the caller sees it being written. That is exactly why the caller
        must not act on a partial stream — half a JSON object parses as nothing, and the half
        that DOES parse is the dangerous case. See api/v1/panel.py.

        A MALFORMED SSE LINE IS SKIPPED, NOT FATAL. These endpoints emit keep-alive comments
        and the occasional empty frame, and dying on one would turn a cosmetic protocol detail
        into a failed interview turn.
        """
        model = request.model_override or self._model
        payload: dict = {
            "model": model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
            # THE USAGE FRAME. Without this the SSE stream ends with `[DONE]` and no token
            # counts at all, so a streamed call would be spend the ledger cannot see. Servers
            # that do not recognise the option ignore it — the terminator below is then built
            # from what was actually received, which is honest about being an estimate rather
            # than silently reporting zero.
            "stream_options": {"include_usage": True},
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}

        log = logger.bind(provider=self.provider_name, model=model, streaming=True)
        try:
            async with self._client.stream(
                "POST", _CHAT_COMPLETIONS_PATH, json=payload
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread())[:500].decode("utf-8", "replace")
                    log.error("provider_stream_api_error", status_code=response.status_code)
                    raise ProviderError(
                        f"{self.provider_name} API returned {response.status_code}: {body}",
                        provider=self.provider_name,
                        status_code=response.status_code,
                        raw_error=body,
                    )
                whole: list[str] = []
                usage: dict = {}
                finish = "stop"
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    # The usage frame arrives with an EMPTY choices list, so it has to be read
                    # before the choices are indexed rather than after.
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    try:
                        choice = chunk["choices"][0]
                    except (KeyError, IndexError, TypeError):
                        continue
                    finish = choice.get("finish_reason") or finish
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        whole.append(delta)
                        yield StreamChunk(text=delta)

                # THE TERMINATOR. Yielded only after the loop ran to completion, so a stream
                # that was cut leaves none and the caller can tell a finished answer from a
                # truncated one that happens to look complete.
                #
                # `prompt_tokens` FALLS BACK TO A CHARACTER ESTIMATE rather than to zero when
                # the server sent no usage frame. Zero is not a smaller number here, it is a
                # false one: it would report this call as free, and the margin sheet built on
                # `ai_usage` would quietly understate the cost of every streamed turn. A rough
                # figure that is roughly right is the honest answer, and the 4-characters-per-
                # token ratio is the same one tests/test_prompt_caching.py already uses.
                content = "".join(whole)
                yield StreamChunk(
                    final=ProviderResponse(
                        content=content,
                        model=model,
                        prompt_tokens=int(
                            usage.get("prompt_tokens")
                            or sum(len(m.content) for m in request.messages) / 4
                        ),
                        completion_tokens=int(
                            usage.get("completion_tokens") or len(content) / 4
                        ),
                        finish_reason=finish,
                    )
                )
        except httpx.TimeoutException as exc:
            log.error("provider_stream_timeout", error=str(exc))
            raise ProviderError(
                f"{self.provider_name} stream timed out after {exc}",
                provider=self.provider_name,
            ) from exc
        except httpx.RequestError as exc:
            # RAISED FROM INSIDE THE ITERATION. A stream cut half way through has produced
            # text that looks like an answer, and the raise is the only thing that
            # distinguishes it from a finished one.
            log.error("provider_stream_network_error", error=str(exc))
            raise ProviderError(
                f"{self.provider_name} network error: {exc}", provider=self.provider_name
            ) from exc

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        model = request.model_override or self._model

        payload: dict = {
            "model": model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}

        log = logger.bind(
            provider=self.provider_name,
            model=model,
            message_count=len(request.messages),
            json_mode=request.json_mode,
            max_tokens=request.max_tokens,
        )
        log.debug("provider_request_start")

        try:
            response = await self._client.post(_CHAT_COMPLETIONS_PATH, json=payload)
        except httpx.TimeoutException as exc:
            log.error("provider_timeout", error=str(exc))
            raise ProviderError(
                f"{self.provider_name} request timed out after {exc}",
                provider=self.provider_name,
            ) from exc
        except httpx.RequestError as exc:
            log.error("provider_network_error", error=str(exc))
            raise ProviderError(
                f"{self.provider_name} network error: {exc}",
                provider=self.provider_name,
            ) from exc

        if response.status_code != 200:
            error_body = response.text[:500]
            log.error(
                "provider_api_error",
                status_code=response.status_code,
                body=error_body,
            )
            raise ProviderError(
                f"{self.provider_name} API returned {response.status_code}: {error_body}",
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
                f"Unexpected {self.provider_name} response shape: {str(data)[:200]}",
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
            "provider_request_complete",
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
            logger.exception("provider_health_check_failed", provider=self.provider_name)
            return False

    async def close(self) -> None:
        await self._client.aclose()


# Backwards-compatible name -- existing imports/log messages referenced "GLM"
# specifically before this became a shared generic implementation.
GLMProvider = OpenAICompatibleProvider
