from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as to_markdown

from backend.skills.base import SkillContext
from backend.skills.http_fetch import pinned_getaddrinfo
from backend.skills.models import ScrapePageInput, ScrapePageOutput
from backend.skills.safety import (
    FETCH_TIMEOUT_SECONDS,
    MAX_DOWNLOAD_BYTES,
    MAX_REDIRECTS,
    MIN_HOST_INTERVAL_SECONDS,
    USER_AGENT,
    SafetyError,
    resolve_fetch_url,
    validate_fetch_url,
)

CHAR_LIMIT = 12_000
SHORT_TEXT_CHARS = 200

_fetch_lock = asyncio.Lock()
_pin_lock = asyncio.Lock()
_last_host_at: dict[str, float] = {}


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def apply_length_limit(text: str, limit: int = CHAR_LIMIT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _page_title(html: str) -> str:
    parser = _TitleParser()
    try:
        parser.feed(html)
    except Exception:
        return ""
    return parser.title.strip()


def _markdownify_body(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.body or soup
    markdown = to_markdown(str(body), heading_style="ATX", strip=["script", "style"])
    return (markdown or "").strip()


def html_to_markdown(html: str) -> tuple[str, str]:
    extracted = ""
    try:
        import trafilatura

        extracted = (
            trafilatura.extract(
                html,
                include_links=True,
                include_tables=True,
                output_format="markdown",
            )
            or ""
        ).strip()
    except Exception:
        extracted = ""

    if len(extracted) >= SHORT_TEXT_CHARS:
        return extracted, "trafilatura"

    fallback = _markdownify_body(html)
    if fallback:
        return fallback, "markdownify"
    return extracted, "trafilatura"


def _rendered_hint() -> str | None:
    from backend.skills.registry import default_registry

    return "scrape_rendered" if default_registry.get("scrape_rendered") else None


async def _respect_host_interval(host: str) -> None:
    now = time.monotonic()
    last = _last_host_at.get(host, 0.0)
    wait = MIN_HOST_INTERVAL_SECONDS - (now - last)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_host_at[host] = time.monotonic()


async def _read_limited(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_DOWNLOAD_BYTES:
            raise SafetyError("response too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def scrape_page(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    cancel_event: asyncio.Event | None = None,
    resolver: Callable[..., Any] | None = None,
    rate_limit: bool = True,
    empty_hint: str | None = None,
) -> ScrapePageOutput:
    try:
        kwargs = {} if resolver is None else {"resolver": resolver}
        validate_fetch_url(url, **kwargs)
    except SafetyError as exc:
        return ScrapePageOutput(url=url, error=str(exc))

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=FETCH_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )

    current = url
    html = ""
    final_url = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError()
            host = urlparse(current).hostname or ""
            if rate_limit:
                async with _fetch_lock:
                    await _respect_host_interval(host)
            try:
                target = resolve_fetch_url(current, **kwargs)
            except SafetyError as exc:
                return ScrapePageOutput(url=current, error=str(exc))
            try:
                pin_lock = _pin_lock if owns_client else contextlib.nullcontext()
                pin_dns = pinned_getaddrinfo(target) if owns_client else contextlib.nullcontext()
                async with pin_lock:
                    with pin_dns:
                        async with client.stream("GET", current) as response:
                            if response.is_redirect:
                                location = response.headers.get("location")
                                if not location:
                                    return ScrapePageOutput(url=current, error="redirect without location")
                                nxt = urljoin(str(response.url), location)
                                try:
                                    validate_fetch_url(nxt, **kwargs)
                                except SafetyError as exc:
                                    return ScrapePageOutput(url=current, error=f"redirect blocked: {exc}")
                                current = nxt
                                continue
                            if response.status_code >= 400:
                                return ScrapePageOutput(
                                    url=str(response.url),
                                    error=f"HTTP {response.status_code}",
                                )
                            raw = await _read_limited(response)
                            html = raw.decode(response.encoding or "utf-8", errors="replace")
                            final_url = str(response.url)
                            break
            except httpx.TimeoutException:
                return ScrapePageOutput(url=current, error="timeout")
            except httpx.RequestError as exc:
                return ScrapePageOutput(url=current, error=f"request failed: {exc}")
        else:
            return ScrapePageOutput(url=url, error="too many redirects")
    finally:
        if owns_client:
            await client.aclose()

    markdown, _method = html_to_markdown(html)

    markdown, truncated = apply_length_limit(markdown)
    title = _page_title(html)
    if not markdown:
        hint = empty_hint if empty_hint is not None else _rendered_hint()
        return ScrapePageOutput(
            url=final_url,
            title=title,
            error="empty content: 页面几乎没有可读正文。常见原因是需要登录、内容由脚本渲染，或站点拦截了抓取。当前版本不支持登录态抓取。",
            hint=hint,
        )
    return ScrapePageOutput(url=final_url, title=title, markdown=markdown, truncated=truncated)


class ScrapePageSkill:
    name = "scrape_page"
    description = "Fetch a public http(s) page and extract main content as Markdown. Use this for ordinary articles, docs, and list pages. Do not use it first for video download or image galleries."
    input_model = ScrapePageInput
    extras = None
    routing = "普通公开网页用 scrape_page。不要未试静态抓取就改用渲染类工具。"

    def available(self) -> bool:
        return True

    async def run(self, args: dict[str, Any], context: SkillContext) -> ScrapePageOutput:
        return await scrape_page(
            args["url"],
            cancel_event=context.cancel_event,
            empty_hint=_rendered_hint(),
        )
