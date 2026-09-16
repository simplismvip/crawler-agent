from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from backend.agent.engine import run_agent
from backend.agent.llm import ScriptedLLM, StreamPart
from backend.skills.models import ScrapePageOutput


class DummyOut(BaseModel):
    markdown: str = "ok"
    error: str | None = None


def _tool_fragments(call_id: str, name: str, arguments: str) -> list[StreamPart]:
    mid = max(1, len(arguments) // 2)
    return [
        StreamPart(tool_index=0, tool_id=call_id, tool_name=name, arguments_delta=arguments[:mid]),
        StreamPart(tool_index=0, arguments_delta=arguments[mid:]),
    ]


async def _collect(message: str, llm: ScriptedLLM, runner) -> list[Any]:
    return [event async for event in run_agent(message, llm=llm, tool_runner=runner, request_id="req")]


def _tool_messages(payload: list[dict]) -> list[dict]:
    return [item for item in payload if item.get("role") == "tool"]


@pytest.mark.asyncio
async def test_single_tool_call_appends_assistant_then_tool() -> None:
    llm = ScriptedLLM(
        rounds=[
            _tool_fragments("call_1", "scrape_page", '{"url": "https://example.com"}'),
            [StreamPart(text="done")],
        ]
    )

    async def runner(name: str, args: dict, _cancel) -> BaseModel:
        assert name == "scrape_page"
        assert args["url"] == "https://example.com"
        return ScrapePageOutput(url=args["url"], markdown="hello world")

    events = await _collect("抓取 https://example.com", llm, runner)
    kinds = [event.event for event in events]
    assert kinds[0] == "tool_start"
    assert events[0].args == {"url": "https://example.com"}
    assert "token" not in kinds[:1]
    assert kinds[-1] == "done"
    assert events[-1].status == "complete"

    second = llm.seen_messages[1]
    assistant = next(item for item in reversed(second) if item["role"] == "assistant" and item.get("tool_calls"))
    tools = _tool_messages(second)
    assert len(assistant["tool_calls"]) == 1
    assert len(tools) == 1
    assert tools[0]["tool_call_id"] == "call_1"
    assert assistant["tool_calls"][0]["id"] == "call_1"


@pytest.mark.asyncio
async def test_parallel_tool_calls_all_get_responses() -> None:
    llm = ScriptedLLM(
        rounds=[
            [
                StreamPart(tool_index=0, tool_id="c1", tool_name="search_web", arguments_delta='{"query": "a"}'),
                StreamPart(tool_index=1, tool_id="c2", tool_name="scrape_page", arguments_delta='{"url": "https://example.com"}'),
            ],
            [StreamPart(text="sum")],
        ]
    )
    seen: list[str] = []

    async def runner(name: str, args: dict, _cancel) -> BaseModel:
        seen.append(name)
        return DummyOut(markdown=name)

    events = await _collect("search then scrape", llm, runner)
    assert seen == ["search_web", "scrape_page"]
    second = llm.seen_messages[1]
    assistant = next(item for item in second if item.get("tool_calls"))
    tools = _tool_messages(second)
    assert [tc["id"] for tc in assistant["tool_calls"]] == ["c1", "c2"]
    assert [item["tool_call_id"] for item in tools] == ["c1", "c2"]
    assert [event.event for event in events].count("tool_start") == 2


@pytest.mark.asyncio
async def test_invalid_json_still_writes_tool_response() -> None:
    llm = ScriptedLLM(
        rounds=[
            [
                StreamPart(
                    tool_index=0,
                    tool_id="bad",
                    tool_name="scrape_page",
                    arguments_delta='{"url":',
                )
            ],
            [StreamPart(text="explain")],
        ]
    )

    async def runner(*_args):
        raise AssertionError("must not execute")

    events = await _collect("x", llm, runner)
    ends = [event for event in events if event.event == "tool_end"]
    assert ends[0].status == "error"
    tools = _tool_messages(llm.seen_messages[1])
    assert len(tools) == 1
    assert tools[0]["tool_call_id"] == "bad"
    assert "tool_start" not in [event.event for event in events]
