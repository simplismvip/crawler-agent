from __future__ import annotations

import httpx
import pytest

from backend.skills.models import ScrapePageOutput
from backend.skills.scraper import apply_length_limit, html_to_markdown, scrape_page

HN_HTML = """
<html><head><title>Hacker News</title></head>
<body>
<table>
  <tr class="athing"><td><span class="titleline"><a href="https://example.com/one">Story One</a></span></td></tr>
  <tr class="athing"><td><span class="titleline"><a href="https://example.com/two">Story Two</a></span></td></tr>
  <tr class="athing"><td><span class="titleline"><a href="https://example.com/three">Story Three</a></span></td></tr>
</table>
</body></html>
"""

ARTICLE_HTML = """
<html><head><title>Doc</title></head>
<body>
  <article>
    <h1>Fastify upgrade notes</h1>
    <p>This document explains the breaking changes in the latest major release of Fastify.</p>
    <p>Route prefixing now requires an explicit option and plugins must declare their metadata.</p>
    <p>Please read the migration guide before upgrading production services.</p>
    <p>Additional paragraphs exist so heuristic extractors can detect a real article body with enough text density.</p>
  </article>
</body></html>
"""


def test_list_page_falls_back_to_markdownify_without_browser() -> None:
    markdown, method = html_to_markdown(HN_HTML)
    assert method == "markdownify"
    assert "Story One" in markdown
    assert "https://example.com/one" in markdown
    assert "Story Two" in markdown


def test_article_page_uses_trafilatura() -> None:
    markdown, method = html_to_markdown(ARTICLE_HTML)
    assert method == "trafilatura"
    assert "breaking changes" in markdown.lower() or "Fastify" in markdown


def test_truncation_flags_long_text() -> None:
    huge = "<html><body>" + "".join(f"<p>paragraph {i} " + ("word " * 80) + "</p>" for i in range(400)) + "</body></html>"
    markdown, _method = html_to_markdown(huge)
    clipped, truncated = apply_length_limit(markdown)
    assert truncated is True
    assert len(clipped) <= 12000


@pytest.mark.asyncio
async def test_scrape_page_returns_404_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="missing")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await scrape_page(
            "https://example.com/missing",
            client=client,
            resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
            rate_limit=False,
        )
    assert isinstance(result, ScrapePageOutput)
    assert result.error
    assert "404" in result.error


@pytest.mark.asyncio
async def test_scrape_empty_shell_explains_login_or_js_wall() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><head><title>小红书 - 你的生活兴趣社区</title></head><body><div id='app'></div></body></html>",
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await scrape_page(
            "https://example.com/app",
            client=client,
            resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
            rate_limit=False,
        )
    assert result.error
    assert "登录" in result.error
    assert not result.markdown
    from backend.skills.registry import default_registry

    if default_registry.get("scrape_rendered"):
        assert result.hint == "scrape_rendered"
    else:
        assert result.hint is None


@pytest.mark.asyncio
async def test_scrape_empty_shell_hints_rendered_when_provided() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><head><title>App</title></head><body><div id='app'></div></body></html>",
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await scrape_page(
            "https://example.com/app",
            client=client,
            resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
            rate_limit=False,
            empty_hint="scrape_rendered",
        )
    assert result.error
    assert result.hint == "scrape_rendered"
    assert not result.markdown
