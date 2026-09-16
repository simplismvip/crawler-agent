from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.media import (
    COMPATIBLE_VIDEO_FORMAT,
    _collect_downloaded_files,
    _yt_dlp_opts,
    download_media,
)
from backend.skills.models import DownloadMediaInput, DownloadMediaOutput
from backend.skills.registry import default_registry
from backend.skills.safety import SafetyError, sandbox_download_dir


def test_download_media_schema_has_info_only_not_request_id() -> None:
    props = DownloadMediaInput.model_json_schema()["properties"]
    assert "info_only" in props
    assert props["info_only"]["default"] is True
    assert "request_id" not in props


def test_sandbox_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(SafetyError):
        sandbox_download_dir("../etc", root=tmp_path)
    dest = sandbox_download_dir("abc-123", root=tmp_path)
    assert dest.is_dir()
    assert dest.parent == tmp_path.resolve()


@pytest.mark.asyncio
async def test_download_media_info_only_skips_files() -> None:
    async def backend(url: str, **kwargs) -> DownloadMediaOutput:
        assert kwargs["info_only"] is True
        assert kwargs["dest_dir"] is None
        return DownloadMediaOutput(url=url, title="Demo", captions="hello subtitle", extractor="mock")

    result = await download_media(
        "https://example.com/watch",
        info_only=True,
        backend=backend,
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.title == "Demo"
    assert result.captions == "hello subtitle"
    assert result.files == []


def test_yt_dlp_opts_prefer_h264_mp4() -> None:
    opts = _yt_dlp_opts(audio_only=False, info_only=False, dest_dir=None)
    assert opts["format"] == COMPATIBLE_VIDEO_FORMAT
    assert opts["merge_output_format"] == "mp4"
    audio = _yt_dlp_opts(audio_only=True, info_only=False, dest_dir=None)
    assert audio["format"] == "bestaudio/best"
    assert "merge_output_format" not in audio


def test_collect_downloaded_files_from_dest_dir(tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x" * 10)
    (tmp_path / "ignore.txt").write_text("no")
    files = _collect_downloaded_files(
        {}, dest_dir=tmp_path, audio_only=False, info_only=False
    )
    assert len(files) == 1
    assert files[0].path.endswith("demo.mp4")
    assert files[0].bytes == 10
    assert files[0].media_type == "video"


@pytest.mark.asyncio
async def test_download_media_rejects_loopback() -> None:
    async def backend(*_a, **_k) -> DownloadMediaOutput:
        raise AssertionError("must not run")

    result = await download_media("http://127.0.0.1/video", backend=backend)
    assert result.error
