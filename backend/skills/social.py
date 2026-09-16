from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from backend.skills.base import SkillContext
from backend.skills.cookies import CookieJar, has_login_sentinels
from backend.skills.models import ScrapeSocialInput, ScrapeSocialOutput
from backend.skills.safety import SafetyError, validate_fetch_url
from backend.skills.scraper import apply_length_limit, truncation_task_warning

PLATFORMS = ("xhs", "bili", "dy", "wb")


class SocialAdapter(Protocol):
    def installed(self) -> bool: ...

    async def scrape(self, url: str, platform: str, cookie_path: Path | None) -> ScrapeSocialOutput: ...


class EnvAdapter:
    def installed(self) -> bool:
        home = os.environ.get("MEDIACRAWLER_HOME", "").strip()
        return bool(home) and Path(home).is_dir()

    async def scrape(self, url: str, platform: str, cookie_path: Path | None) -> ScrapeSocialOutput:
        return ScrapeSocialOutput(
            url=url,
            platform=platform,
            error="MediaCrawler adapter is a stub in V1.2; provide cookies and a local install to enable later.",
        )


def infer_platform(url: str, explicit: str | None) -> str | None:
    if explicit:
        key = explicit.strip().lower()
        return key if key in PLATFORMS else None
    host = (urlparse(url).hostname or "").lower()
    if "xiaohongshu" in host or host.endswith("xhs.com"):
        return "xhs"
    if "bilibili" in host:
        return "bili"
    if "douyin" in host:
        return "dy"
    if "weibo" in host:
        return "wb"
    return None


def cookie_path_for(platform: str) -> Path | None:
    jar = CookieJar()
    state = jar.load_storage_state(platform)
    cookies = list((state or {}).get("cookies") or [])
    if not has_login_sentinels(platform, cookies):
        return None
    return jar.storage_path(platform)


async def scrape_social(
    url: str,
    *,
    platform: str | None = None,
    adapter: SocialAdapter | None = None,
    resolver=None,
) -> ScrapeSocialOutput:
    try:
        kwargs = {} if resolver is None else {"resolver": resolver}
        validate_fetch_url(url, **kwargs)
    except SafetyError as exc:
        return ScrapeSocialOutput(url=url, error=str(exc))

    resolved = infer_platform(url, platform)
    if resolved is None:
        return ScrapeSocialOutput(url=url, error="unsupported social platform")

    worker = adapter or EnvAdapter()
    cookie = cookie_path_for(resolved)
    if cookie is None:
        return ScrapeSocialOutput(
            url=url,
            platform=resolved,
            error="当前不能带登录态抓取。请运行 python -m tools.login --platform {platform}，或将 storage_state 放到 data/cookies/{platform}.json。".format(
                platform=resolved
            ),
        )
    result = await worker.scrape(url, resolved, cookie)
    if result.markdown:
        markdown, truncated = apply_length_limit(result.markdown)
        result.markdown = markdown
        result.truncated = truncated
        result.warning = truncation_task_warning(truncated)
    return result


class SocialSkill:
    name = "scrape_social"
    description = (
        "Fetch Xiaohongshu/Douyin/Weibo/Bilibili content via a local MediaCrawler install. "
        "Requires cookies. Do not use scrape_page or scrape_rendered on login walls."
    )
    input_model = ScrapeSocialInput
    extras = "social"
    routing = (
        "小红书/抖音/微博/B 站内容页且 scrape_social 可用时用它，"
        "不要用静态抓取去撞登录墙。"
        "无登录态时说明运行 python -m tools.login --platform xhs，禁止改调 scrape_rendered。"
    )

    def __init__(self, adapter: SocialAdapter | None = None) -> None:
        self._adapter = adapter or EnvAdapter()

    def available(self) -> bool:
        return self._adapter.installed()

    async def run(self, args: dict[str, Any], context: SkillContext) -> ScrapeSocialOutput:
        return await scrape_social(
            args["url"],
            platform=args.get("platform"),
            adapter=self._adapter,
        )
