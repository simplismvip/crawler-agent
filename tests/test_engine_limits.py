from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from backend.agent.engine import run_agent
from backend.agent.llm import ScriptedLLM, StreamPart


class DummyOut(BaseModel):
    markdown: str = "ok"
    error: str | None = None


@pytest.mark.asyncio
async def test_max_tool_calls_still_returns_all_tool_ids_and_done() -> None:
    llm = ScriptedLLM(
        rounds=[
            [
                StreamPart(tool_index=0, tool_id="a", tool_name="search_web", arguments_delta='{"query": "q"}'),
                StreamPart(tool_index=1, tool_id="b", tool_name="scrape_page", arguments_delta='{"url": "https://example.com"}'),
            ],
            [StreamPart(text="summary")],
        ]
    )
    executed: list[str] = []

    async def runner(name: str, args: dict, _cancel) -> BaseModel:
        executed.append(name)
        return DummyOut(markdown=name)

    events = [
        event
        async for event in run_agent(
            "q",
            llm=llm,
            tool_runner=runner,
            max_tool_calls=1,
            request_id="req",
        )
    ]
    assert executed == ["search_web"]
    second = llm.seen_messages[1]
    tool_ids = [item["tool_call_id"] for item in second if item.get("role") == "tool"]
    assert tool_ids == ["a", "b"]
    assert events[-1].event == "done"
    assert "none" in llm.tool_choices


@pytest.mark.asyncio
async def test_forced_summary_after_round_limit() -> None:
    llm = ScriptedLLM(
        rounds=[
            [
                StreamPart(
                    tool_index=0,
                    tool_id="only",
                    tool_name="search_web",
                    arguments_delta='{"query": "q"}',
                )
            ],
            [StreamPart(text="final")],
        ]
    )

    async def runner(name: str, args: dict, _cancel) -> BaseModel:
        return DummyOut(markdown="hit")

    events = [
        event
        async for event in run_agent(
            "q",
            llm=llm,
            tool_runner=runner,
            max_llm_rounds=1,
            request_id="req",
        )
    ]
    assert events[-1].event == "done"
    assert events[-1].status == "complete"
    assert llm.tool_choices[-1] == "none"
    assert any(event.event == "token" and event.text == "final" for event in events)


@pytest.mark.asyncio
async def test_cancel_event_stops_in_flight_tool() -> None:
    started = asyncio.Event()
    cancel = asyncio.Event()
    llm = ScriptedLLM(
        rounds=[
            [
                StreamPart(
                    tool_index=0,
                    tool_id="c",
                    tool_name="search_web",
                    arguments_delta='{"query": "q"}',
                )
            ],
            [StreamPart(text="nope")],
        ]
    )

    async def runner(name: str, args: dict, _cancel) -> BaseModel:
        started.set()
        await asyncio.sleep(30)
        return DummyOut()

    async def consume() -> None:
        async for _event in run_agent(
            "q",
            llm=llm,
            tool_runner=runner,
            cancel_event=cancel,
            request_id="r",
        ):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=2)
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
