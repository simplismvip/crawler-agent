from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.agent.engine import run_agent
from backend.agent.schema import (
    ChatRequest,
    ConversationEvent,
    DoneEvent,
    ErrorEvent,
    PingEvent,
)
from backend.models_catalog import DEFAULT_MODEL, MODELS, resolve_model
from backend.settings import settings
from backend.store import ConversationRecord, ConversationStore, MessageRecord, ToolCallRecord

app = FastAPI(title="Crawler Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = ConversationStore(settings.sqlite_path)

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class ConversationCreate(BaseModel):
    model: str | None = None


class ConversationRename(BaseModel):
    title: str


def _authorize(request: Request) -> None:
    if not settings.api_token:
        return
    header = request.headers.get("authorization", "")
    token = request.headers.get("x-api-token", "")
    if header == f"Bearer {settings.api_token}" or token == settings.api_token:
        return
    raise HTTPException(status_code=401, detail="unauthorized")


def format_sse(event) -> str:
    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"


def _tool_json(tool: ToolCallRecord) -> dict[str, Any]:
    return {
        "id": tool.id,
        "name": tool.name,
        "args": tool.args,
        "status": tool.status,
        "preview": tool.preview,
        "error": tool.error,
    }


def _message_json(message: MessageRecord) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "tools": [_tool_json(tool) for tool in message.tools],
    }


def _conversation_json(record: ConversationRecord, *, messages: bool = False) -> dict[str, Any]:
    payload = {
        "id": record.id,
        "title": record.title,
        "model": record.model,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    if messages:
        payload["messages"] = [_message_json(message) for message in record.messages]
    return payload


def _parse_model(requested: str | None) -> str:
    try:
        return resolve_model(requested, settings.openai_model or DEFAULT_MODEL)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unknown model: {exc}") from exc


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    return {"default": DEFAULT_MODEL, "models": [dict(item) for item in MODELS]}


@app.get("/api/skills")
async def list_skills() -> dict[str, Any]:
    from backend.skills.registry import default_registry

    return {"skills": [item.model_dump() for item in default_registry.skill_infos()]}


@app.get("/api/conversations")
async def list_conversations(request: Request, q: str | None = None) -> dict[str, Any]:
    _authorize(request)
    return {"conversations": [_conversation_json(item) for item in store.list_conversations(q)]}


@app.post("/api/conversations")
async def create_conversation(body: ConversationCreate, request: Request) -> dict[str, Any]:
    _authorize(request)
    model = _parse_model(body.model)
    return _conversation_json(store.create_conversation(model=model))


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request) -> dict[str, Any]:
    _authorize(request)
    record = store.get_conversation(conversation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return _conversation_json(record, messages=True)


@app.patch("/api/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, body: ConversationRename, request: Request) -> dict[str, Any]:
    _authorize(request)
    if store.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    store.rename_conversation(conversation_id, body.title)
    record = store.get_conversation(conversation_id)
    assert record is not None
    return _conversation_json(record)


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request) -> Response:
    _authorize(request)
    if not store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    return Response(status_code=204)


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    _authorize(request)
    request_id = uuid.uuid4().hex
    cancel_event = asyncio.Event()
    model = _parse_model(body.model)
    if body.conversation_id:
        existing = store.get_conversation(body.conversation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        conversation = existing
        history = store.history_turns(conversation.id)
        store.touch(conversation.id, model=model)
    else:
        conversation = store.create_conversation(model=model)
        history = list(body.history)
    store.add_message(conversation.id, "user", body.message)
    title = store.set_title_from_first_message(conversation.id)
    assistant = store.add_message(conversation.id, "assistant", "")

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def produce() -> None:
            pending_tools: list[str] = []
            chunks: list[str] = []
            try:
                await queue.put(
                    ConversationEvent(
                        request_id=request_id,
                        conversation_id=conversation.id,
                        title=title,
                        model=model,
                    )
                )
                async for event in run_agent(
                    body.message,
                    history,
                    request_id=request_id,
                    cancel_event=cancel_event,
                    model=model,
                ):
                    if event.event == "token":
                        chunks.append(event.text)
                    elif event.event == "error":
                        chunks.append(event.message)
                    elif event.event == "tool_start":
                        record = store.add_tool_call(
                            assistant.id,
                            name=event.name,
                            args=event.args,
                            status="running",
                        )
                        pending_tools.append(record.id)
                    elif event.event == "tool_end" and pending_tools:
                        tool_id = pending_tools.pop(0)
                        store.update_tool_call(
                            tool_id,
                            status=event.status,
                            preview=event.preview,
                            error=event.error,
                        )
                    await queue.put(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await queue.put(ErrorEvent(request_id=request_id, message=str(exc)))
                await queue.put(DoneEvent(request_id=request_id, status="error"))
            finally:
                store.update_message_content(assistant.id, "".join(chunks))
                await queue.put(None)

        task = asyncio.create_task(produce())
        sent_done = False
        agent_started = False
        last_ping = time.monotonic()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Starlette often reports POST SSE as disconnected before any
                    # body byte. conversation/ping do not count — otherwise a
                    # slow MiniMax first token gets cancelled as "Connection error."
                    if agent_started and await request.is_disconnected():
                        cancel_event.set()
                        break
                    if time.monotonic() - last_ping >= 15:
                        yield format_sse(PingEvent(request_id=request_id))
                        last_ping = time.monotonic()
                    continue
                if event is None:
                    break
                if event.event not in {"conversation", "ping"}:
                    agent_started = True
                if event.event == "done":
                    sent_done = True
                yield format_sse(event)
                if sent_done:
                    break
        finally:
            cancel_event.set()
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            if not sent_done:
                yield format_sse(DoneEvent(request_id=request_id, status="error"))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
