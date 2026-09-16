from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from backend.skills.base import SkillContext
from backend.skills.models import DownloadMediaInput, DownloadMediaOutput, MediaFile
from backend.skills.safety import SafetyError, sandbox_download_dir, validate_fetch_url
from backend.skills.scraper import apply_length_limit

MediaBackend = Callable[..., Awaitable[DownloadMediaOutput]]
INFO_TIMEOUT_SECONDS = 20.0
DOWNLOAD_TIMEOUT_SECONDS = 120.0
MAX_MEDIA_BYTES = 200 * 1024 * 1024
# Bilibili/YouTube often pick AV1 as "best"; Finder/QuickTime/课件 usually need H.264.
COMPATIBLE_VIDEO_FORMAT = (
    "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/"
    "bv*[vcodec^=avc]+ba/"
    "b[ext=mp4][vcodec^=avc1]/"
    "bv*+ba/b"
)
MEDIA_SUFFIXES = {".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus", ".wav", ".mov"}


async def download_media(
    url: str,
    *,
    audio_only: bool = False,
    info_only: bool = True,
    dest_dir: Path | None = None,
    backend: MediaBackend | None = None,
    resolver=None,
    cancel_event: asyncio.Event | None = None,
) -> DownloadMediaOutput:
    try:
        kwargs = {} if resolver is None else {"resolver": resolver}
        validate_fetch_url(url, **kwargs)
    except SafetyError as exc:
        return DownloadMediaOutput(url=url, error=str(exc))

    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError()

    timeout = INFO_TIMEOUT_SECONDS if info_only else DOWNLOAD_TIMEOUT_SECONDS
    worker = backend or _yt_dlp_backend
    try:
        result = await asyncio.wait_for(
            worker(url, audio_only=audio_only, info_only=info_only, dest_dir=dest_dir),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return DownloadMediaOutput(url=url, error="timeout")
    except Exception as exc:
        return DownloadMediaOutput(url=url, error=str(exc))

    captions, truncated = apply_length_limit(result.captions or "")
    description, desc_trunc = apply_length_limit(result.description or "")
    result.captions = captions
    result.description = description
    if truncated or desc_trunc:
        # keep files; caption truncation is silent besides length
        pass
    return result


def _yt_dlp_opts(
    *,
    audio_only: bool,
    info_only: bool,
    dest_dir: Path | None,
    cookiefile: Path | None = None,
    cookies_from_browser: str | None = None,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": info_only,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["zh", "zh-Hans", "en", "en.*"],
    }
    if audio_only:
        opts["format"] = "bestaudio/best"
    else:
        opts["format"] = COMPATIBLE_VIDEO_FORMAT
        opts["merge_output_format"] = "mp4"
    if dest_dir is not None and not info_only:
        dest_dir.mkdir(parents=True, exist_ok=True)
        opts["outtmpl"] = str(dest_dir / "%(title).80s.%(ext)s")
        opts["max_filesize"] = MAX_MEDIA_BYTES
    if cookiefile is not None and Path(cookiefile).is_file():
        opts["cookiefile"] = str(cookiefile)
    elif cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


def _session_for_url(url: str) -> tuple[Path | None, str | None]:
    from backend.skills.cookies import CookieJar

    cookiefile = CookieJar().netscape_for_url(url)
    if cookiefile is not None:
        return cookiefile, None
    browser = (os.getenv("COOKIES_FROM_BROWSER") or "").strip()
    return None, browser or None


def _collect_downloaded_files(
    info: dict[str, Any],
    *,
    dest_dir: Path | None,
    audio_only: bool,
    info_only: bool,
) -> list[MediaFile]:
    files: list[MediaFile] = []
    seen: set[str] = set()

    def add(path: Path, media_type: str) -> None:
        if len(files) >= 3 or not path.exists() or path.suffix.lower() not in MEDIA_SUFFIXES:
            return
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        files.append(
            MediaFile(path=str(path), media_type=media_type, bytes=path.stat().st_size)
        )

    default_type = "audio" if audio_only else "video"
    for item in info.get("requested_downloads") or []:
        filepath = item.get("filepath") or item.get("filename")
        if filepath:
            add(Path(filepath), default_type)
    for key in ("filepath", "_filename", "filename"):
        raw = info.get(key)
        if raw:
            add(Path(str(raw)), default_type)
    if not files and dest_dir is not None and not info_only and dest_dir.exists():
        for path in sorted(dest_dir.iterdir()):
            if path.name.endswith(".part"):
                continue
            suffix = path.suffix.lower()
            media_type = "audio" if audio_only or suffix in {".m4a", ".mp3", ".opus", ".wav"} else "video"
            add(path, media_type)
    return files


async def _yt_dlp_backend(
    url: str,
    *,
    audio_only: bool,
    info_only: bool,
    dest_dir: Path | None,
) -> DownloadMediaOutput:
    import yt_dlp

    cookiefile, from_browser = _session_for_url(url)
    opts = _yt_dlp_opts(
        audio_only=audio_only,
        info_only=info_only,
        dest_dir=dest_dir,
        cookiefile=cookiefile,
        cookies_from_browser=from_browser,
    )

    def _extract() -> DownloadMediaOutput:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=not info_only)
        if not info:
            return DownloadMediaOutput(url=url, error="no media info")
        files = _collect_downloaded_files(
            info, dest_dir=dest_dir, audio_only=audio_only, info_only=info_only
        )
        captions = ""
        subtitles = info.get("subtitles") or info.get("automatic_captions") or {}
        for lang in ("zh", "zh-Hans", "en"):
            tracks = subtitles.get(lang) or []
            if tracks and isinstance(tracks, list) and tracks[0].get("data"):
                captions = str(tracks[0]["data"])
                break
        return DownloadMediaOutput(
            url=url,
            title=info.get("title") or "",
            extractor=info.get("extractor") or "",
            duration=info.get("duration"),
            uploader=info.get("uploader") or info.get("channel") or "",
            description=info.get("description") or "",
            captions=captions,
            files=files,
        )

    return await asyncio.to_thread(_extract)


class MediaSkill:
    name = "download_media"
    description = (
        "Get video metadata/subtitles, or download the media file via the built-in yt-dlp. "
        "Set info_only=false to save the file locally. Never tell the user to run yt-dlp or you-get themselves."
    )
    input_model = DownloadMediaInput
    extras = "media"
    routing = (
        "视频标题/UP主/字幕/「讲了什么」用 download_media 且 info_only=true。"
        "用户要下载、保存、拿到视频文件、离线、放进课件时，必须 download_media 且 info_only=false，"
        "成功后用工具返回的 path 告诉用户文件在哪。"
        "若刚才 info_only=true 且 files 为空、用户其实要文件，下一步立刻再调且 info_only=false。"
        "历史里出现 Connection error 或「下载失败」时，用户再说下载/重新下载，仍必须立刻 download_media 且 info_only=false，禁止只复述旧错误。"
        "禁止建议 you-get、唧唧Down、浏览器插件或让用户自己跑 yt-dlp。"
        "若下载因登录墙失败，告知用户 python -m tools.login --platform bili 或放入 Cookie 文件，不要建议给日常 Chrome 开远程调试。"
    )

    def available(self) -> bool:
        try:
            import yt_dlp  # noqa: F401
        except ImportError:
            return False
        return True

    async def run(self, args: dict[str, Any], context: SkillContext) -> DownloadMediaOutput:
        dest = None
        info_only = bool(args.get("info_only", True))
        if not info_only:
            dest = sandbox_download_dir(context.request_id)
        return await download_media(
            args["url"],
            audio_only=bool(args.get("audio_only", False)),
            info_only=info_only,
            dest_dir=dest,
            cancel_event=context.cancel_event,
        )
