from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass
class StreamPart:
    text: str | None = None
    tool_index: int | None = None
    tool_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str | None = None


@dataclass
class ScriptedLLM:
    rounds: list[list[StreamPart]]
    seen_messages: list[list[dict]] = field(default_factory=list)
    tool_choices: list[str] = field(default_factory=list)

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        tool_choice: str = "auto",
    ) -> AsyncIterator[StreamPart]:
        self.seen_messages.append([dict(item) for item in messages])
        self.tool_choices.append(tool_choice)
        if not self.rounds:
            return
        for part in self.rounds.pop(0):
            yield part
