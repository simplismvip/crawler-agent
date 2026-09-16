from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from backend.settings import settings
from backend.skills.base import SkillContext
from backend.skills.models import SearchHit, SearchWebInput, SearchWebOutput
from backend.skills.safety import USER_AGENT

SearchBackend = Callable[[str, int], Awaitable[SearchWebOutput]]


def _hits_from_rows(rows: list[dict], max_results: int) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for item in rows:
        url = item.get("url") or item.get("href") or ""
        if not url:
            continue
        hits.append(
            SearchHit(
                title=item.get("title") or "",
                url=url,
                snippet=item.get("content") or item.get("snippet") or item.get("body") or "",
            )
        )
        if len(hits) >= max_results:
            break
    return hits


async def _search_searxng(
    query: str,
    max_results: int,
    *,
    base_url: str,
    client: httpx.AsyncClient | None = None,
) -> SearchWebOutput:
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT})
    try:
        response = await client.get(
            f"{base_url.rstrip('/')}/search",
            params={
                "q": query,
                "format": "json",
                "language": "zh-CN",
                "categories": "general",
            },
        )
        if response.status_code >= 400:
            return SearchWebOutput(query=query, error=f"searxng HTTP {response.status_code}")
        payload = response.json()
    except httpx.RequestError as exc:
        return SearchWebOutput(query=query, error=f"searxng request failed: {exc}")
    except ValueError as exc:
        return SearchWebOutput(query=query, error=f"searxng invalid json: {exc}")
    finally:
        if owns_client:
            await client.aclose()
    return SearchWebOutput(query=query, results=_hits_from_rows(payload.get("results") or [], max_results))


async def _search_tavily(query: str, max_results: int) -> SearchWebOutput:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.search_api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
        )
        if response.status_code >= 400:
            return SearchWebOutput(query=query, error=f"search HTTP {response.status_code}")
        payload = response.json()
    return SearchWebOutput(query=query, results=_hits_from_rows(payload.get("results") or [], max_results))


async def _search_duckduckgo(query: str, max_results: int) -> SearchWebOutput:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return SearchWebOutput(query=query, error="no search backend configured")

    def _run() -> list[SearchHit]:
        with DDGS() as ddgs:
            rows = list(ddgs.text(query, max_results=max_results))
        return _hits_from_rows(rows, max_results)

    try:
        import asyncio

        hits = await asyncio.to_thread(_run)
    except Exception as exc:
        return SearchWebOutput(query=query, error=f"search failed: {exc}")
    return SearchWebOutput(query=query, results=hits)


async def search_web(
    query: str,
    max_results: int = 3,
    *,
    backend: SearchBackend | None = None,
) -> SearchWebOutput:
    clamped = max(1, min(5, max_results))
    if backend is not None:
        return await backend(query, clamped)
    if settings.searxng_base_url:
        return await _search_searxng(query, clamped, base_url=settings.searxng_base_url)
    if settings.search_api_key:
        return await _search_tavily(query, clamped)
    return await _search_duckduckgo(query, clamped)


def parse_search_args(raw: dict) -> SearchWebInput:
    return SearchWebInput.model_validate(raw)


class SearchWebSkill:
    name = "search_web"
    description = "Search the public web and return title/url/snippet hits."
    input_model = SearchWebInput
    extras = None
    routing = "没有 URL 时先 search_web，再挑选 1 个最相关结果交给抓取工具；确有必要时最多再打开 1 个页面。"

    def available(self) -> bool:
        return True

    async def run(self, args: dict, context: SkillContext) -> SearchWebOutput:
        return await search_web(args["query"], args.get("max_results", 3))

