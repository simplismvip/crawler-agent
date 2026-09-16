from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from backend.skills.base import SkillContext
from backend.skills.models import DownloadGalleryInput, DownloadGalleryOutput, MediaFile
from backend.skills.safety import SafetyError, sandbox_download_dir, validate_fetch_url

GalleryBackend = Callable[..., Awaitable[DownloadGalleryOutput]]
MAX_ITEMS = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def clamp_max_items(value: int) -> int:
    return max(1, min(MAX_ITEMS, value))


async def download_gallery(
    url: str,
    *,
    max_items: int = 12,
    dest_dir: Path | None = None,
    backend: GalleryBackend | None = None,
    resolver=None,
    cancel_event: asyncio.Event | None = None,
) -> DownloadGalleryOutput:
    try:
        kwargs = {} if resolver is None else {"resolver": resolver}
        validate_fetch_url(url, **kwargs)
    except SafetyError as exc:
        return DownloadGalleryOutput(url=url, error=str(exc))

    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError()

    clamped = clamp_max_items(max_items)
    worker = backend or _gallery_dl_backend
    cookiefile = _cookiefile_for_url(url)
    try:
        result = await worker(url, max_items=clamped, dest_dir=dest_dir, cookiefile=cookiefile)
    except Exception as exc:
        return DownloadGalleryOutput(url=url, error=str(exc))
    if len(result.files) > clamped:
        result.files = result.files[:clamped]
        result.truncated = True
    return result


def _cookiefile_for_url(url: str) -> Path | None:
    from backend.skills.cookies import CookieJar

    return CookieJar().netscape_for_url(url)


async def _gallery_dl_backend(
    url: str,
    *,
    max_items: int,
    dest_dir: Path | None,
    cookiefile: Path | None = None,
) -> DownloadGalleryOutput:
    import gallery_dl

    dest = dest_dir or Path(".")
    dest.mkdir(parents=True, exist_ok=True)
    job = gallery_dl.job.DownloadJob(url)
    extra = {"directory": [str(dest)]}
    if cookiefile is not None and Path(cookiefile).is_file():
        extra["cookies"] = str(cookiefile)
    job.extractor.config = {**(getattr(job.extractor, "config", None) or {}), **extra}
    files: list[MediaFile] = []

    def _run() -> DownloadGalleryOutput:
        # Best-effort adapter: collect extracted paths without requiring a live site in tests.
        for item in job.extractor:
            path = dest / Path(str(item.get("filename") or item.get("num") or len(files))).name
            if path.exists() and path.stat().st_size > MAX_IMAGE_BYTES:
                continue
            files.append(MediaFile(path=str(path), media_type="image", bytes=path.stat().st_size if path.exists() else 0))
            if len(files) >= max_items:
                break
        return DownloadGalleryOutput(url=url, files=files, truncated=False)

    return await asyncio.to_thread(_run)


class GallerySkill:
    name = "download_gallery"
    description = "Download an image gallery/album. Do not use on ordinary articles."
    input_model = DownloadGalleryInput
    extras = "gallery"
    routing = "图集、相册、时间线多图用 download_gallery。不要对普通文章页调用。禁止让用户自己安装 gallery-dl。"

    def available(self) -> bool:
        try:
            import gallery_dl  # noqa: F401
        except ImportError:
            return False
        return True

    async def run(self, args: dict[str, Any], context: SkillContext) -> DownloadGalleryOutput:
        dest = sandbox_download_dir(context.request_id)
        return await download_gallery(
            args["url"],
            max_items=int(args.get("max_items", 12)),
            dest_dir=dest,
            cancel_event=context.cancel_event,
        )
