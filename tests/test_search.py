from __future__ import annotations

import pytest

from backend.skills.models import SearchHit, SearchWebOutput
from backend.skills.search import _search_searxng, search_web


@pytest.mark.asyncio
async def test_search_web_uses_injected_backend() -> None:
    async def backend(query: str, max_results: int) -> SearchWebOutput:
        return SearchWebOutput(
            query=query,
            results=[SearchHit(title="Fastify", url="https://example.com/docs", snippet="changelog")][:max_results],
        )

    output = await search_web("fastify", backend=backend)
    assert output.results[0].url == "https://example.com/docs"
    assert output.error is None


@pytest.mark.asyncio
async def test_search_web_clamps_max_results() -> None:
    seen: list[int] = []

    async def backend(query: str, max_results: int) -> SearchWebOutput:
        seen.append(max_results)
        return SearchWebOutput(query=query, results=[])

    await search_web("q", max_results=99, backend=backend)
    assert seen == [5]


@pytest.mark.asyncio
async def test_searxng_parses_json_results() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("q") == "fastify"
        assert request.url.params.get("format") == "json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Fastify docs",
                        "url": "https://fastify.dev/docs",
                        "content": "Fastify changelog",
                    },
                    {"title": "skip me", "url": "", "content": ""},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        output = await _search_searxng(
            "fastify",
            3,
            base_url="http://127.0.0.1:8080",
            client=client,
        )
    assert output.error is None
    assert len(output.results) == 1
    assert output.results[0].url == "https://fastify.dev/docs"
    assert "changelog" in output.results[0].snippet
