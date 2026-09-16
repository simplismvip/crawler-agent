from __future__ import annotations

import pytest
from pydantic import BaseModel, TypeAdapter

from backend.agent.engine import run_agent
from backend.agent.llm import ScriptedLLM, StreamPart
from backend.agent.schema import AgentEvent, DoneEvent, ToolEndEvent
from backend.skills.models import ScrapePageOutput


@pytest.mark.asyncio
async def test_tool_failure_still_emits_done_complete() -> None:
    llm = ScriptedLLM(
        rounds=[
            [
                StreamPart(
                    tool_index=0,
                    tool_id="call",
                    tool_name="scrape_page",
                    arguments_delta='{"url": "https://example.com"}',
                )
            ],
            [StreamPart(text="抓取失败")],
        ]
    )

    async def runner(name: str, args: dict, _cancel) -> BaseModel:
        return ScrapePageOutput(url=args["url"], error="HTTP 404")

    events = [event async for event in run_agent("x", llm=llm, tool_runner=runner, request_id="r")]
    adapter = TypeAdapter(AgentEvent)
    for event in events:
        adapter.validate_python(event.model_dump())
    ends = [event for event in events if isinstance(event, ToolEndEvent)]
    assert ends[0].status == "error"
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].status == "complete"
    assert not any(event.event == "error" for event in events)
