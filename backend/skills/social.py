from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from backend.settings import ROOT
from backend.skills.base import SkillContext
from backend.skills.cookies import CookieJar, is_logged_in
from backend.skills.models import ScrapeSocialInput, ScrapeSocialOutput
from backend.skills.safety import SafetyError, validate_fetch_url
from backend.skills.scraper import apply_length_limit, truncation_task_warning

PLATFORMS = ("xhs", "bili", "dy", "wb", "zhihu")
SOCIAL_TIMEOUT_SECONDS = 120.0
Runner = Callable[[list[str], Path, float], Awaitable[tuple[int, str]]]

_COOKIE_VALUE_RE = re.compile(
    r"(?i)\b(?:web_session|a1|id_token|z_c0|webId|sid_guard|--cookies)\s*[=:\s]\s*\S+"
)
_XHS_NOTE_PATH = re.compile(
    r"^/(?:explore|discovery/item)/[0-9a-zA-Z]+$",
)
_XHS_PROFILE_PATH = re.compile(r"^/user/profile/[0-9a-zA-Z]+$")

_TITLE_KEYS = ("title", "note_title", "question_title", "aweme_id")
_AUTHOR_KEYS = ("nickname", "user_nickname", "author", "user_name", "name")
_BODY_KEYS = ("desc", "content", "note_desc", "ip_location")
_URL_KEYS = ("note_url", "url", "aweme_url", "video_url", "content_url")


class SocialAdapter(Protocol):
    def installed(self) -> bool: ...

    async def scrape(self, url: str, platform: str, cookie_path: Path | None) -> ScrapeSocialOutput: ...


def mediacrawler_home() -> Path | None:
    raw = (os.environ.get("MEDIACRAWLER_HOME") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_dir() and (path / "main.py").is_file():
        return path
    return None


def social_url_error(platform: str, url: str) -> str | None:
    if platform != "xhs":
        return None
    parsed = urlparse(url)
    path = (parsed.path or "").rstrip("/") or "/"
    token = (parse_qs(parsed.query).get("xsec_token") or [""])[0].strip()
    if path in ("/", "/explore", "/discovery", "/search"):
        return (
            "这是小红书面板/首页，不是笔记或创作者页。"
            "请给笔记详情 https://www.xiaohongshu.com/explore/<笔记id>?xsec_token=..."
            "或创作者主页 https://www.xiaohongshu.com/user/profile/<用户id>?xsec_token=..."
            "不要改用 collect_dataset（那是 JSON 列表落盘，不是 HTML 首页）。"
        )
    if _XHS_NOTE_PATH.match(path) or _XHS_PROFILE_PATH.match(path):
        if token:
            return None
        return (
            "小红书笔记/创作者 URL 需要带 xsec_token 查询参数，"
            "请从浏览器地址栏复制完整链接，不要只用 /explore 首页。"
            "不要改用 collect_dataset。"
        )
    return (
        "无法识别为小红书笔记或创作者 URL。"
        "请提供带 xsec_token 的笔记链接（/explore/{id}?xsec_token=...）"
        "或创作者主页（/user/profile/{id}?xsec_token=...）。"
        "不要改用 collect_dataset。"
    )


def _sanitize_mc_output(output: str) -> str:
    lines = []
    for raw in (output or "").splitlines():
        if "--cookies" in raw.lower() or "cookie" in raw.lower():
            continue
        cleaned = _COOKIE_VALUE_RE.sub("[redacted]", raw).strip()
        if cleaned:
            lines.append(cleaned)
    text = " ".join(lines[-8:])
    return text[-400:]


def public_mc_error(output: str, code: int) -> str:
    text = output or ""
    lower = text.lower()
    base = f"MediaCrawler 失败（exit {code}）。已带登录 Cookie，不是没登录。"
    if "executable doesn't exist" in lower or "playwright install" in lower:
        extra = (
            " Playwright 浏览器未安装。在 MEDIACRAWLER_HOME 目录运行："
            "`.venv/bin/playwright install chromium-headless-shell`。"
        )
    elif "datafetcherror" in lower:
        extra = (
            " 小红书接口返回 DataFetchError（站点拒绝或限流），不是 URL 不支持。"
            "用户主页比单条笔记更容易被拦；笔记详情（/explore 或 /discovery/item 带 xsec_token）通常更稳。"
        )
    else:
        snippet = _sanitize_mc_output(text)
        extra = f" 日志：{snippet}" if snippet else ""
    return (
        base
        + extra
        + " 不要再跑 tools.login，也不要用 collect_dataset 去抓 HTML 首页（那是 JSON 列表落盘工具）。"
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
    if "zhihu.com" in host:
        return "zhihu"
    return None


def cookie_path_for(platform: str) -> Path | None:
    jar = CookieJar()
    state = jar.load_storage_state(platform)
    if not is_logged_in(platform, state):
        return None
    return jar.storage_path(platform)


def _pick(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            name = val.get("name") or val.get("nickname")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return ""


def records_to_markdown(payload: Any) -> str:
    items: list[Any]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        nested = None
        for key in ("data", "contents", "items", "notes"):
            if isinstance(payload.get(key), list):
                nested = payload[key]
                break
        items = nested if nested is not None else [payload]
    else:
        return ""
    blocks: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        title = _pick(raw, _TITLE_KEYS)
        author = _pick(raw, _AUTHOR_KEYS)
        body = _pick(raw, _BODY_KEYS)
        source = _pick(raw, _URL_KEYS)
        lines: list[str] = []
        if title:
            lines.append(f"## {title}")
        if author:
            lines.append(f"作者：{author}")
        if source:
            lines.append(f"来源：{source}")
        if body:
            lines.append("")
            lines.append(body)
        if lines:
            blocks.append("\n".join(lines).strip())
    return "\n\n".join(blocks).strip()


def markdown_from_save_dir(save_dir: Path) -> str:
    if not save_dir.is_dir():
        return ""
    files = sorted(
        list(save_dir.rglob("*.json")) + list(save_dir.rglob("*.jsonl")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    chunks: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            continue
        if path.suffix == ".jsonl":
            rows = []
            for line in text.splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            md = records_to_markdown(rows)
        else:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            md = records_to_markdown(payload)
        if md:
            chunks.append(md)
    return "\n\n".join(chunks).strip()


def is_xhs_creator_url(url: str) -> bool:
    path = (urlparse(url).path or "").rstrip("/")
    return bool(_XHS_PROFILE_PATH.match(path))


def build_mediacrawler_args(
    *,
    platform: str,
    url: str,
    cookies: str,
    save_path: str | Path,
) -> list[str]:
    creator = platform == "xhs" and is_xhs_creator_url(url)
    flags = [
        "--platform",
        platform,
        "--lt",
        "cookie",
        "--type",
        "creator" if creator else "detail",
    ]
    if creator:
        flags.extend(["--creator_id", url])
        max_notes = "10"
    else:
        flags.extend(["--specified_id", url])
        max_notes = "1"
    flags.extend(
        [
            "--cookies",
            cookies,
            "--save_data_option",
            "json",
            "--save_data_path",
            str(save_path),
            "--get_comment",
            "no",
            "--get_sub_comment",
            "no",
            "--headless",
            "yes",
            "--crawler_max_notes_count",
            max_notes,
        ]
    )
    return flags


def _cookie_header(url: str, cookie_path: Path | None) -> str:
    header = CookieJar().cookie_header(url)
    if header:
        return header
    if cookie_path is None or not cookie_path.is_file():
        return ""
    try:
        data = json.loads(cookie_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    parts = []
    for item in data.get("cookies") or []:
        name = item.get("name")
        if name:
            parts.append(f"{name}={item.get('value') or ''}")
    return "; ".join(parts)


def _launch_argv(home: Path, flags: list[str]) -> list[str]:
    runner = ROOT / "tools" / "mediacrawler_run.py"
    venv_py = home / ".venv" / "bin" / "python"
    if venv_py.is_file():
        return [str(venv_py), str(runner), *flags]
    return ["uv", "run", "--directory", str(home), "python", str(runner), *flags]


async def _default_run(flags: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    argv = _launch_argv(cwd, flags)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "MEDIACRAWLER_HOME": str(cwd)},
    )
    try:
        out_b, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return 124, "timeout"
    text = (out_b or b"").decode("utf-8", errors="replace")
    return int(proc.returncode or 0), text


class EnvAdapter:
    def __init__(self, runner: Runner | None = None) -> None:
        self._runner = runner or _default_run

    def installed(self) -> bool:
        return mediacrawler_home() is not None

    async def scrape(self, url: str, platform: str, cookie_path: Path | None) -> ScrapeSocialOutput:
        home = mediacrawler_home()
        if home is None:
            return ScrapeSocialOutput(
                url=url,
                platform=platform,
                error="MediaCrawler 未安装。请克隆仓库并设置 MEDIACRAWLER_HOME。",
            )
        cookies = _cookie_header(url, cookie_path)
        if not cookies:
            return ScrapeSocialOutput(
                url=url,
                platform=platform,
                error=f"当前不能带登录态抓取。请运行 python -m tools.login --platform {platform}",
            )
        with tempfile.TemporaryDirectory(prefix="mc-") as tmp:
            save = Path(tmp)
            flags = build_mediacrawler_args(
                platform=platform,
                url=url,
                cookies=cookies,
                save_path=save,
            )
            code, output = await self._runner(flags, home, SOCIAL_TIMEOUT_SECONDS)
            if code != 0:
                return ScrapeSocialOutput(
                    url=url,
                    platform=platform,
                    error=public_mc_error(output, code),
                )
            markdown = markdown_from_save_dir(save)
        if not markdown:
            return ScrapeSocialOutput(
                url=url,
                platform=platform,
                error="MediaCrawler 没有写出可读内容。",
            )
        return ScrapeSocialOutput(url=url, platform=platform, markdown=markdown)


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
    url_err = social_url_error(resolved, url)
    if url_err:
        return ScrapeSocialOutput(url=url, platform=resolved, error=url_err)

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
        "Fetch Xiaohongshu note details (/explore/{id}?xsec_token=) or creator "
        "profiles (/user/profile/{id}?xsec_token=), plus Douyin/Weibo/Bilibili/Zhihu, "
        "via MediaCrawler. Requires cookies. Do not refuse Xiaohongshu user/profile URLs; "
        "do not use scrape_page or scrape_rendered on login walls."
    )
    input_model = ScrapeSocialInput
    extras = "social"
    routing = (
        "小红书/抖音/微博/B 站/知乎内容页且 scrape_social 可用时用它，"
        "不要用静态抓取去撞登录墙。"
        "小红书必须给笔记详情（/explore/{id}?xsec_token=）或创作者主页（/user/profile/{id}?xsec_token=），禁止用首页 /explore。"
        "禁止声称不支持 user/profile；用户给出主页时必须调用本工具。"
        "失败后按错误原文说明，禁止改 collect_dataset，禁止再 login。"
        "无登录态时说明运行 python -m tools.login --platform xhs|zhihu|…，禁止改调 scrape_rendered。"
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
