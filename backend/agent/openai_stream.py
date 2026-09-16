from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from openai import APIConnectionError, APIError, AsyncOpenAI

from backend.agent.llm import StreamPart
from backend.settings import settings

CONNECT_ATTEMPTS = 3


class OpenAIStreamer:
    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None) -> None:
        self.client = client or AsyncOpenAI(
            api_key=settings.openai_api_key or "missing",
            base_url=settings.openai_base_url,
        )
        self.model = model or settings.openai_model

    async def _create_once(self, kwargs: dict[str, Any]) -> Any:
        try:
            return await self.client.chat.completions.create(**kwargs)
        except APIConnectionError:
            raise
        except APIError as exc:
            message = str(exc)
            if "parallel_tool_calls" in message and "parallel_tool_calls" in kwargs:
                kwargs.pop("parallel_tool_calls")
                return await self.client.chat.completions.create(**kwargs)
            if "thinking" in message and "extra_body" in kwargs:
                kwargs.pop("extra_body")
                return await self.client.chat.completions.create(**kwargs)
            raise

    async def _create(self, kwargs: dict[str, Any]) -> Any:
        last_error: BaseException | None = None
        for attempt in range(CONNECT_ATTEMPTS):
            try:
                return await self._create_once(kwargs)
            except APIConnectionError as exc:
                last_error = exc
                if attempt == CONNECT_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(0.4 * (attempt + 1))
        assert last_error is not None
        raise last_error

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_choice: str = "auto",
    ) -> AsyncIterator[StreamPart]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tool_choice != "none":
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
            kwargs["parallel_tool_calls"] = False
        else:
            kwargs["tool_choice"] = "none"
        if settings.is_minimax:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        stream = await self._create(kwargs)

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield StreamPart(text=delta.content)
            for tool_call in delta.tool_calls or []:
                function = tool_call.function
                yield StreamPart(
                    tool_index=tool_call.index,
                    tool_id=tool_call.id,
                    tool_name=function.name if function else None,
                    arguments_delta=function.arguments if function and function.arguments else None,
                )
