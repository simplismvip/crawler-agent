from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.agent.engine import run_agent
from backend.agent.schema import ChatRequest, DoneEvent, ErrorEvent, PingEvent
from backend.settings import settings

app = FastAPI(title="Crawler Agent V1.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


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


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    _authorize(request)
    request_id = uuid.uuid4().hex
    cancel_event = asyncio.Event()

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def produce() -> None:
            try:
                async for event in run_agent(
                    body.message,
                    body.history,
                    request_id=request_id,
                    cancel_event=cancel_event,
                ):
                    await queue.put(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await queue.put(ErrorEvent(request_id=request_id, message=str(exc)))
                await queue.put(DoneEvent(request_id=request_id, status="error"))
            finally:
                await queue.put(None)

        task = asyncio.create_task(produce())
        sent_done = False
        got_event = False
        last_ping = time.monotonic()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Starlette reports POST streams as disconnected before the
                    # first byte. Only probe after the agent has started emitting.
                    if got_event and await request.is_disconnected():
                        cancel_event.set()
                        break
                    if time.monotonic() - last_ping >= 15:
                        yield format_sse(PingEvent(request_id=request_id))
                        last_ping = time.monotonic()
                    continue
                if event is None:
                    break
                got_event = True
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
