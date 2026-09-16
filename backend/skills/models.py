from __future__ import annotations

from pydantic import BaseModel, Field


class SearchWebInput(BaseModel):
    query: str
    max_results: int = Field(default=3, ge=1, le=5)


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""


class SearchWebOutput(BaseModel):
    query: str
    results: list[SearchHit] = Field(default_factory=list)
    error: str | None = None


class ScrapePageInput(BaseModel):
    url: str


class ScrapePageOutput(BaseModel):
    url: str
    title: str = ""
    markdown: str = ""
    truncated: bool = False
    error: str | None = None
