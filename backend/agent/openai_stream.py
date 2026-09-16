from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import APIError, AsyncOpenAI

from backend.agent.llm import StreamPart
from backend.settings import settings


class OpenAIStreamer:
    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None) -> None:
        self.client = client or AsyncOpenAI(
            api_key=settings.openai_api_key or "missing",
            base_url=settings.openai_base_url,
        )
        self.model = model or settings.openai_model

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

        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except APIError as exc:
            message = str(exc)
            if "parallel_tool_calls" in message and "parallel_tool_calls" in kwargs:
                kwargs.pop("parallel_tool_calls")
                stream = await self.client.chat.completions.create(**kwargs)
            elif "thinking" in message and "extra_body" in kwargs:
                kwargs.pop("extra_body")
                stream = await self.client.chat.completions.create(**kwargs)
            else:
                raise

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
