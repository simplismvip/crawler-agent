from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from backend.skills.base import SkillContext
from backend.skills.cookies import (
    CookieJar,
    LOGIN_ERROR,
    detect_login_wall,
    has_login_sentinels,
    infer_platform,
)
from backend.skills.http_fetch import pinned_getaddrinfo
from backend.skills.models import CollectDatasetInput, CollectDatasetOutput
from backend.skills.safety import (
    FETCH_TIMEOUT_SECONDS,
    MAX_DOWNLOAD_BYTES,
    MAX_REDIRECTS,
    MIN_HOST_INTERVAL_SECONDS,
    USER_AGENT,
    SafetyError,
    resolve_fetch_url,
    sandbox_download_dir,
    validate_fetch_url,
)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_ZHIHU_QUESTION_RE = re.compile(
    r"^https?://(?:www\.)?zhihu\.com/question/(\d+)(?:/)?(?:\?.*)?$",
    re.I,
)

MAX_ITEMS = 200

FetchFn = Callable[[str], Awaitable[tuple[int, str, str]]]

_fetch_lock = asyncio.Lock()
_pin_lock = asyncio.Lock()
_last_host_at: dict[str, float] = {}


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


async def _httpx_fetch(
    url: str,
    *,
    client: httpx.AsyncClient,
    jar: CookieJar,
    resolver=None,
    owns_client: bool = False,
    rate_limit: bool = True,
    cancel_event: asyncio.Event | None = None,
) -> tuple[int, str, str]:
    kwargs = {} if resolver is None else {"resolver": resolver}
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError()
        host = urlparse(current).hostname or ""
        if rate_limit:
            async with _fetch_lock:
                await _respect_host_interval(host)
        target = resolve_fetch_url(current, **kwargs)
        pin_lock = _pin_lock if owns_client else contextlib.nullcontext()
        pin_dns = pinned_getaddrinfo(target) if owns_client else contextlib.nullcontext()
        extra_headers: dict[str, str] = {}
        cookie_header = jar.cookie_header(current)
        if cookie_header:
            extra_headers["Cookie"] = cookie_header
        if "/api/" in (urlparse(current).path or ""):
            extra_headers["Accept"] = "application/json"
        async with pin_lock:
            with pin_dns:
                async with client.stream("GET", current, headers=extra_headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise SafetyError("redirect without location")
                        nxt = urljoin(str(response.url), location)
                        validate_fetch_url(nxt, **kwargs)
                        current = nxt
                        continue
                    raw = await _read_limited(response)
                    body = raw.decode(response.encoding or "utf-8", errors="replace")
                    content_type = response.headers.get("content-type", "")
                    return response.status_code, content_type, body
    raise SafetyError("too many redirects")

FIELD_ALIASES: dict[str, str] = {
    "正文": "content",
    "内容": "content",
    "回答": "content",
    "作者": "author",
    "答主": "author",
    "UP 主": "author",
    "up 主": "author",
    "up主": "author",
    "标题": "title",
    "时间": "published_at",
    "日期": "published_at",
    "点赞": "voteup_count",
    "赞同": "voteup_count",
}


def _normalize_field(name: str) -> str:
    stripped = name.strip()
    if stripped in FIELD_ALIASES:
        return FIELD_ALIASES[stripped]
    lowered = stripped.lower()
    if lowered in FIELD_ALIASES:
        return FIELD_ALIASES[lowered]
    return lowered.replace(" ", "_")


def normalize_fields(fields: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for field in fields:
        normalized = _normalize_field(field)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def clamp_max_items(value: int) -> int:
    return max(1, min(MAX_ITEMS, int(value)))


def rewrite_list_url(url: str) -> str:
    """Map a few HTML list pages onto their JSON APIs. Skill itself is site-agnostic."""
    if "/api/" in url:
        return url
    match = _ZHIHU_QUESTION_RE.match(url)
    if not match:
        return url
    question_id = match.group(1)
    return (
        f"https://www.zhihu.com/api/v3/question/{question_id}/answers"
        f"?limit=20&offset=0&order_by=default"
    )


def _html_title(html: str) -> str:
    match = _TITLE_RE.search(html or "")
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def extract_json_page(payload: Any) -> tuple[list[Any], str | None]:
    if isinstance(payload, list):
        return payload, None
    if not isinstance(payload, dict):
        return [], None
    data = payload.get("data")
    if not isinstance(data, list):
        return [], None
    next_url: str | None = None
    paging = payload.get("paging")
    if isinstance(paging, dict) and not paging.get("is_end"):
        nxt = paging.get("next")
        if isinstance(nxt, str) and nxt:
            next_url = nxt
    return data, next_url


def project_item(raw: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for field in fields:
        if field == "author":
            author = raw.get("author")
            if isinstance(author, dict):
                projected["author"] = author.get("name")
            else:
                projected["author"] = author
        elif field == "content":
            projected["content"] = raw.get("content") or raw.get("excerpt")
        elif field == "url":
            projected["url"] = raw.get("url")
        else:
            projected[field] = raw.get(field)
    if "url" not in projected:
        projected["url"] = raw.get("url")
    return projected


async def collect_dataset(
    url: str,
    *,
    fields: list[str],
    max_items: int = 50,
    format: str = "json",
    dest_dir: Path | None = None,
    fetch: FetchFn | None = None,
    resolver=None,
    cancel_event: asyncio.Event | None = None,
    cookie_jar: CookieJar | None = None,
    client: httpx.AsyncClient | None = None,
    rate_limit: bool = True,
) -> CollectDatasetOutput:
    try:
        kwargs = {} if resolver is None else {"resolver": resolver}
        validate_fetch_url(url, **kwargs)
    except SafetyError as exc:
        return CollectDatasetOutput(url=url, error=str(exc))

    jar = cookie_jar if cookie_jar is not None else CookieJar()
    platform = infer_platform(url)
    if platform:
        state = jar.load_storage_state(platform)
        cookies = list((state or {}).get("cookies") or [])
        if not has_login_sentinels(platform, cookies):
            return CollectDatasetOutput(
                url=url,
                error=f"{LOGIN_ERROR}。请运行 python -m tools.login --platform {platform}",
            )

    if format != "json":
        return CollectDatasetOutput(url=url, error=f"unsupported format: {format}")
    if dest_dir is None:
        return CollectDatasetOutput(url=url, error="dest_dir required")

    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError()

    owns_client = False
    active_client = client
    if fetch is None:
        owns_client = active_client is None
        if active_client is None:
            active_client = httpx.AsyncClient(
                follow_redirects=False,
                timeout=FETCH_TIMEOUT_SECONDS,
                headers={"User-Agent": USER_AGENT},
            )

        async def _default_fetch(current_url: str) -> tuple[int, str, str]:
            assert active_client is not None
            return await _httpx_fetch(
                current_url,
                client=active_client,
                jar=jar,
                resolver=resolver,
                owns_client=owns_client,
                rate_limit=rate_limit,
                cancel_event=cancel_event,
            )

        fetch = _default_fetch

    try:
        return await _collect_pages(
            url,
            fields=fields,
            max_items=max_items,
            dest_dir=dest_dir,
            fetch=fetch,
            kwargs=kwargs,
            cancel_event=cancel_event,
        )
    except httpx.TimeoutException:
        return CollectDatasetOutput(url=url, error="timeout")
    except httpx.RequestError as exc:
        return CollectDatasetOutput(url=url, error=f"request failed: {exc}")
    except SafetyError as exc:
        return CollectDatasetOutput(url=url, error=str(exc))
    finally:
        if owns_client and active_client is not None:
            await active_client.aclose()


async def _collect_pages(
    url: str,
    *,
    fields: list[str],
    max_items: int,
    dest_dir: Path,
    fetch: FetchFn,
    kwargs: dict[str, Any],
    cancel_event: asyncio.Event | None,
) -> CollectDatasetOutput:
    normalized = normalize_fields(fields)
    limit = clamp_max_items(max_items)
    rows: list[dict[str, Any]] = []
    current: str | None = rewrite_list_url(url)
    truncated = False

    while current:
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError()

        status, _content_type, body = await fetch(current)
        if status >= 400:
            return CollectDatasetOutput(
                url=url,
                error=f"HTTP {status}。已附带本机登录 Cookie，不是没登录。站点拒绝了本次自动化请求（风控）。这不是缺 Cookie，不要向用户索要 Cookie。",
            )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            title = _html_title(body)
            if detect_login_wall(url=current, title=title, html=body):
                return CollectDatasetOutput(
                    url=url,
                    error=f"{LOGIN_ERROR}。请运行 python -m tools.login",
                )
            return CollectDatasetOutput(url=url, error="无法抽取列表")

        page_items, next_url = extract_json_page(payload)
        if not page_items:
            break

        remaining = limit - len(rows)
        take = page_items[:remaining]
        leftover_on_page = len(page_items) > remaining
        for raw in take:
            item = raw if isinstance(raw, dict) else {}
            rows.append(project_item(item, normalized))

        if leftover_on_page or (len(rows) >= limit and next_url):
            truncated = True
            break
        if next_url:
            try:
                validate_fetch_url(next_url, **kwargs)
            except SafetyError as exc:
                if not rows:
                    return CollectDatasetOutput(url=url, error=str(exc))
                truncated = True
                break
        current = next_url

    if not rows:
        return CollectDatasetOutput(url=url, error="无法抽取列表")

    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / "dataset.json"
    out_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return CollectDatasetOutput(
        url=url,
        path=str(out_path),
        count=len(rows),
        fields=normalized,
        truncated=truncated,
    )


class CollectSkill:
    name = "collect_dataset"
    description = (
        "Collect any list/API into a local JSON file (dataset.json). "
        "Use for large scrape tasks on any site, not a specific website. "
        "Do not return item bodies; return path and count. Cookies attach automatically."
    )
    input_model = CollectDatasetInput
    extras = None
    routing = (
        "用户要保存/导出/全部 N 条结构化数据，或抓取结果 truncated/warning 时用 collect_dataset。"
        "针对任务体量，不限网站，不是知乎专用。"
        "禁止用 scrape_page 把列表全文贴进聊天。"
        "成功后用返回的 path 告诉用户文件在哪。"
    )

    def available(self) -> bool:
        return True

    async def run(self, args: dict[str, Any], context: SkillContext) -> CollectDatasetOutput:
        dest = sandbox_download_dir(context.request_id)
        return await collect_dataset(
            args["url"],
            fields=list(args["fields"]),
            max_items=int(args.get("max_items", 50)),
            format=str(args.get("format", "json")),
            dest_dir=dest,
            cancel_event=context.cancel_event,
        )
