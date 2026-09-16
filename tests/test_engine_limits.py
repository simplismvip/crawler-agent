from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import BaseModel

from backend.agent.engine import _content_for_llm, _fatal_llm_message, _preview_from_output, run_agent
from backend.agent.llm import ScriptedLLM, StreamPart
from backend.skills.models import ScrapePageOutput


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


@pytest.mark.asyncio
async def test_unknown_skill_emits_tool_end_error_without_running() -> None:
    llm = ScriptedLLM(
        rounds=[
            [
                StreamPart(
                    tool_index=0,
                    tool_id="ghost",
                    tool_name="not_a_skill",
                    arguments_delta='{"url": "https://example.com"}',
                )
            ],
            [StreamPart(text="ok")],
        ]
    )
    ran = False

    async def runner(*_args):
        nonlocal ran
        ran = True
        raise AssertionError("unknown skill must not execute")

    events = [
        event
        async for event in run_agent("x", llm=llm, tool_runner=runner, request_id="req")
    ]
    assert ran is False
    ends = [event for event in events if event.event == "tool_end"]
    assert ends[0].status == "error"
    assert ends[0].error == "unknown skill"
    assert "tool_start" not in [event.event for event in events]
    assert events[-1].status == "complete"


def test_preview_omits_hint_but_llm_payload_keeps_it() -> None:
    output = ScrapePageOutput(
        url="https://example.com",
        error="empty content: 页面几乎没有可读正文。",
        hint="scrape_rendered",
    )
    preview, error = _preview_from_output(output)
    assert error
    assert "scrape_rendered" not in preview
    payload = _content_for_llm(output)
    assert "scrape_rendered" in payload


def test_content_for_llm_adds_generic_truncation_warning() -> None:
    output = ScrapePageOutput(url="https://example.com/long", markdown="x" * 10_000)
    payload = json.loads(_content_for_llm(output))
    assert payload["truncated"] is True
    assert "collect_dataset" in payload["warning"]
    assert "不限网站" in payload["warning"]
    assert "zhihu" not in payload["warning"].lower()


def test_preview_prepends_truncation_warning() -> None:
    output = ScrapePageOutput(
        url="https://example.com/long",
        markdown="visible body",
        truncated=True,
        warning="内容过长，贴进聊天会被截断，任务会失败。请改用 collect_dataset 保存到本地 JSON，或只摘要前 N 条。此提醒针对任务体量，不限网站。",
    )
    preview, error = _preview_from_output(output)
    assert error is None
    assert preview.startswith("内容过长")
    assert "collect_dataset" in preview


def test_fatal_llm_message_maps_connection_error() -> None:
    assert _fatal_llm_message(Exception("Connection error.")) == "模型服务暂时连不上，请再试一次。"
    assert _fatal_llm_message(Exception("rate limited")) == "rate limited"

