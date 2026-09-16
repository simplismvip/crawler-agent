from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


class PingEvent(BaseModel):
    event: Literal["ping"] = "ping"
    request_id: str


class TokenEvent(BaseModel):
    event: Literal["token"] = "token"
    request_id: str
    text: str


class ToolStartEvent(BaseModel):
    event: Literal["tool_start"] = "tool_start"
    request_id: str
    name: str
    args: dict[str, Any]


class ToolEndEvent(BaseModel):
    event: Literal["tool_end"] = "tool_end"
    request_id: str
    name: str
    status: Literal["ok", "error"]
    error: str | None = None
    preview: str = ""


class ErrorEvent(BaseModel):
    event: Literal["error"] = "error"
    request_id: str
    message: str


class DoneEvent(BaseModel):
    event: Literal["done"] = "done"
    request_id: str
    status: Literal["complete", "error"]


AgentEvent = Annotated[
    Union[PingEvent, TokenEvent, ToolStartEvent, ToolEndEvent, ErrorEvent, DoneEvent],
    Field(discriminator="event"),
]


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, Any]] = Field(default_factory=list)


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
