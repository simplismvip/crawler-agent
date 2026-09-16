from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.agent.llm import StreamPart
from backend.agent.openai_stream import OpenAIStreamer
from backend.agent.schema import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    ToolEndEvent,
    ToolStartEvent,
    TokenEvent,
)
from backend.skills.base import SkillContext
from backend.skills.registry import SkillErrorOutput, default_registry, openai_tools
from backend.skills.scraper import truncation_task_warning

PREVIEW_LIMIT = 800
LLM_MARKDOWN_LIMIT = 9000
ToolRunner = Callable[[str, dict[str, Any], SkillContext], Awaitable[BaseModel]]


def _fatal_llm_message(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    name = type(exc).__name__
    if "connection error" in text.lower() or name in {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
    }:
        return "模型服务暂时连不上，请再试一次。"
    return text


class AccumulatedCall:
    def __init__(self) -> None:
        self.id = ""
        self.name = ""
        self.arguments = ""


def _preview_from_output(output: BaseModel) -> tuple[str, str | None]:
    data = output.model_dump()
    data.pop("hint", None)
    error = data.get("error")
    if error:
        return str(error)[:PREVIEW_LIMIT], str(error)
    files = data.get("files")
    if isinstance(files, list):
        title = data.get("title") or data.get("url") or ""
        preview = f"{title} · {len(files)} 个文件"
        return preview[:PREVIEW_LIMIT], None
    path = data.get("path")
    count = data.get("count")
    if isinstance(path, str) and path and isinstance(count, int):
        preview = f"已保存 {count} 条 · json\n{path}"
        return preview[:PREVIEW_LIMIT], None
    warning = data.get("warning")
    markdown = data.get("markdown")
    if isinstance(markdown, str) and markdown:
        preview = markdown
        if isinstance(warning, str) and warning:
            preview = f"{warning}\n{markdown}"
        return preview[:PREVIEW_LIMIT], None
    if isinstance(warning, str) and warning:
        return warning[:PREVIEW_LIMIT], None
    dumped = json.dumps(data, ensure_ascii=False)
    return dumped[:PREVIEW_LIMIT], None


def _content_for_llm(output: BaseModel) -> str:
    data = output.model_dump()
    markdown = data.get("markdown")
    if isinstance(markdown, str) and len(markdown) > LLM_MARKDOWN_LIMIT:
        data["markdown"] = markdown[:LLM_MARKDOWN_LIMIT]
        data["truncated"] = True
        if not data.get("warning"):
            data["warning"] = truncation_task_warning(True)
    return json.dumps(data, ensure_ascii=False)


def _validate_args(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    skill = default_registry.get(name)
    if skill is None:
        raise KeyError("unknown skill")
    return skill.input_model.model_validate(raw).model_dump()


async def default_tool_runner(
    name: str,
    args: dict[str, Any],
    context: SkillContext,
) -> BaseModel:
    skill = default_registry.get(name)
    if skill is None:
        return SkillErrorOutput(error="unknown skill")
    return await skill.run(args, context)


async def _run_tool(
    tool_runner: ToolRunner,
    name: str,
    args: dict[str, Any],
    context: SkillContext,
) -> BaseModel:
    cancel_event = context.cancel_event
    if cancel_event is None:
        return await tool_runner(name, args, context)
    tool_task = asyncio.create_task(tool_runner(name, args, context))
    cancel_task = asyncio.create_task(cancel_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {tool_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_task in done:
            tool_task.cancel()
            try:
                await tool_task
            except (asyncio.CancelledError, Exception):
                pass
            raise asyncio.CancelledError()
        cancel_task.cancel()
        return tool_task.result()
    finally:
        if not cancel_task.done():
            cancel_task.cancel()
        if not tool_task.done():
            tool_task.cancel()


async def _collect_round(
    llm: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str,
    request_id: str,
    cancel_event: asyncio.Event | None,
) -> tuple[str, list[AccumulatedCall], list[AgentEvent]]:
    events: list[AgentEvent] = []
    text_parts: list[str] = []
    calls: dict[int, AccumulatedCall] = {}
    async for part in llm.stream(messages, tools, tool_choice=tool_choice):
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError()
        if not isinstance(part, StreamPart):
            continue
        if part.text:
            text_parts.append(part.text)
            events.append(TokenEvent(request_id=request_id, text=part.text))
        if part.tool_index is None:
            continue
        slot = calls.setdefault(part.tool_index, AccumulatedCall())
        if part.tool_id:
            slot.id = part.tool_id
        if part.tool_name:
            slot.name = part.tool_name
        if part.arguments_delta:
            slot.arguments += part.arguments_delta
    ordered = [calls[index] for index in sorted(calls)]
    return "".join(text_parts), ordered, events


async def run_agent(
    message: str,
    history: list[dict[str, Any]] | None = None,
    *,
    request_id: str | None = None,
    cancel_event: asyncio.Event | None = None,
    llm: Any | None = None,
    tool_runner: ToolRunner | None = None,
    max_llm_rounds: int = 8,
    max_tool_calls: int = 6,
    model: str | None = None,
) -> AsyncIterator[AgentEvent]:
    request_id = request_id or uuid.uuid4().hex
    llm = llm or OpenAIStreamer(model=model)
    tool_runner = tool_runner or default_tool_runner
    context = SkillContext(request_id=request_id, cancel_event=cancel_event)
    tools = openai_tools()
    messages: list[dict[str, Any]] = [{"role": "system", "content": default_registry.build_system_prompt()}]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    executed = 0
    fatal_message: str | None = None
    need_forced_summary = False

    try:
        round_index = 0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError()
            if round_index >= max_llm_rounds:
                need_forced_summary = True
            tool_choice = "none" if need_forced_summary else "auto"
            round_index += 1
            try:
                content, calls, events = await _collect_round(
                    llm, messages, tools, tool_choice, request_id, cancel_event
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError() from exc
                fatal_message = _fatal_llm_message(exc)
                yield ErrorEvent(request_id=request_id, message=fatal_message)
                break
            for event in events:
                yield event
            if not calls or need_forced_summary:
                break

            assistant_tool_calls = []
            for call in calls:
                assistant_tool_calls.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": assistant_tool_calls,
                }
            )

            for call in calls:
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError()
                quota_left = executed < max_tool_calls
                parsed: dict[str, Any] | None = None
                parse_error: str | None = None
                try:
                    parsed = json.loads(call.arguments or "")
                    if not isinstance(parsed, dict):
                        parse_error = "tool arguments must be a JSON object"
                        parsed = None
                    elif quota_left:
                        if default_registry.get(call.name) is None:
                            parse_error = "unknown skill"
                            parsed = None
                        else:
                            parsed = _validate_args(call.name, parsed)
                except (json.JSONDecodeError, ValidationError, KeyError) as exc:
                    parse_error = str(exc)
                    parsed = None

                if parse_error is not None or parsed is None:
                    error_text = parse_error or "invalid tool arguments"
                    if not quota_left:
                        error_text = "max_tool_calls exceeded"
                    output_payload = {"error": error_text}
                    yield ToolEndEvent(
                        request_id=request_id,
                        name=call.name or "unknown",
                        status="error",
                        error=error_text,
                        preview=error_text[:PREVIEW_LIMIT],
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(output_payload, ensure_ascii=False),
                        }
                    )
                    continue

                if not quota_left:
                    error_text = "max_tool_calls exceeded"
                    yield ToolEndEvent(
                        request_id=request_id,
                        name=call.name,
                        status="error",
                        error=error_text,
                        preview=error_text,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps({"error": error_text}, ensure_ascii=False),
                        }
                    )
                    continue

                yield ToolStartEvent(request_id=request_id, name=call.name, args=parsed)
                try:
                    output = await _run_tool(tool_runner, call.name, parsed, context)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    output = SkillErrorOutput(error=str(exc))
                executed += 1
                preview, error = _preview_from_output(output)
                status = "error" if error else "ok"
                yield ToolEndEvent(
                    request_id=request_id,
                    name=call.name,
                    status=status,
                    error=error,
                    preview=preview,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": _content_for_llm(output),
                    }
                )

            if executed >= max_tool_calls:
                need_forced_summary = True
                messages.append(
                    {
                        "role": "user",
                        "content": "已达上限，必须基于已有观察给出总结，不要再调用工具。",
                    }
                )
                continue
            if round_index >= max_llm_rounds:
                need_forced_summary = True
                messages.append(
                    {
                        "role": "user",
                        "content": "已达上限，必须基于已有观察给出总结，不要再调用工具。",
                    }
                )
                continue
    except asyncio.CancelledError:
        raise
    finally:
        pass

    if fatal_message:
        yield DoneEvent(request_id=request_id, status="error")
        return
    yield DoneEvent(request_id=request_id, status="complete")
