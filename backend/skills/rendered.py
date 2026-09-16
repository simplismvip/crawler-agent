from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from backend.skills.base import SkillContext
from backend.skills.cookies import CookieJar
from backend.skills.models import ScrapeRenderedInput, ScrapeRenderedOutput
from backend.skills.safety import SafetyError, validate_fetch_url
from backend.skills.scraper import apply_length_limit, truncation_task_warning

RENDER_TIMEOUT_SECONDS = 30.0
Crawler = Callable[[str], Awaitable[str]]


def _markdown_from_crawl4ai_result(result: Any) -> str:
    markdown = getattr(result, "markdown", None)
    if markdown is None:
        return ""
    if isinstance(markdown, str):
        return markdown.strip()
    fit = getattr(markdown, "fit_markdown", None) or getattr(result, "fit_markdown", None)
    raw = getattr(markdown, "raw_markdown", None)
    text = fit or raw or str(markdown)
    return (text or "").strip()


def markdown_from_crawl_result(result: Any) -> tuple[str, str | None]:
    success = getattr(result, "success", True)
    status = getattr(result, "status_code", None)
    error_message = str(getattr(result, "error_message", "") or "").strip()
    if success is False or (isinstance(status, int) and status >= 400):
        detail = error_message or (f"HTTP {status}" if isinstance(status, int) else "render failed")
        return "", detail
    return _markdown_from_crawl4ai_result(result), None


def storage_state_for_render(url: str, jar: CookieJar | None = None) -> dict | None:
    return (jar or CookieJar()).storage_state_for_url(url)


async def _crawl4ai_fetch(url: str) -> str:
    from crawl4ai import AsyncWebCrawler, BrowserConfig

    state = storage_state_for_render(url)
    config = BrowserConfig(storage_state=state) if state else BrowserConfig()
    async with AsyncWebCrawler(config=config) as crawler:
        result = await crawler.arun(url=url)
    markdown, error = markdown_from_crawl_result(result)
    if error:
        raise RuntimeError(error)
    return markdown


async def scrape_rendered(
    url: str,
    *,
    crawler: Crawler | None = None,
    resolver=None,
    cancel_event: asyncio.Event | None = None,
) -> ScrapeRenderedOutput:
    try:
        kwargs = {} if resolver is None else {"resolver": resolver}
        validate_fetch_url(url, **kwargs)
    except SafetyError as exc:
        return ScrapeRenderedOutput(url=url, error=str(exc))

    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError()

    fetch = crawler or _crawl4ai_fetch
    try:
        markdown = await asyncio.wait_for(fetch(url), timeout=RENDER_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return ScrapeRenderedOutput(url=url, error="timeout")
    except Exception as exc:
        return ScrapeRenderedOutput(url=url, error=str(exc))

    markdown = (markdown or "").strip()
    markdown, truncated = apply_length_limit(markdown)
    if not markdown:
        return ScrapeRenderedOutput(
            url=url,
            error="empty content: 渲染后仍没有可读正文。",
        )
    return ScrapeRenderedOutput(
        url=url,
        markdown=markdown,
        truncated=truncated,
        warning=truncation_task_warning(truncated),
    )


class RenderedSkill:
    name = "scrape_rendered"
    description = (
        "Render a JavaScript-heavy page with a headless browser and extract Markdown. "
        "Saved login sessions are attached automatically when present. "
        "Use only after scrape_page returns empty content, or when the user says the page is a SPA. "
        "Do not use this to bypass a login wall; if login is required, tell the user to run tools.login."
    )
    input_model = ScrapeRenderedInput
    extras = "rendered"
    routing = (
        "仅当 scrape_page 返回 empty content / hint=scrape_rendered，或用户明确说是 JS/SPA 页时，"
        "才调用 scrape_rendered。普通文章、文档、HN 列表禁止一上来就渲染。"
        "有登录态时渲染也会自动带上；登录墙不要靠渲染硬撞。"
        "若 truncated 或 warning 非空：提醒聊天装不下，改用 collect_dataset 或只摘要；不限网站。"
    )

    def available(self) -> bool:
        try:
            import crawl4ai  # noqa: F401
        except ImportError:
            return False
        return True

    async def run(self, args: dict[str, Any], context: SkillContext) -> ScrapeRenderedOutput:
        return await scrape_rendered(args["url"], cancel_event=context.cancel_event)
