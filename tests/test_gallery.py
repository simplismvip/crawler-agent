from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.gallery import clamp_max_items, download_gallery
from backend.skills.models import DownloadGalleryOutput, MediaFile
from backend.skills.registry import default_registry


def test_gallery_hidden_without_extra() -> None:
    from backend.skills.gallery import GallerySkill

    if GallerySkill().available():
        pytest.skip("gallery-dl is installed in this environment")
    assert default_registry.get("download_gallery") is None


def test_gallery_clamps_max_items() -> None:
    assert clamp_max_items(99) == 30
    assert clamp_max_items(0) == 1


@pytest.mark.asyncio
async def test_download_gallery_clamps_backend_files() -> None:
    async def backend(url: str, **kwargs) -> DownloadGalleryOutput:
        assert kwargs["max_items"] == 30
        files = [MediaFile(path=f"/tmp/{i}.jpg", media_type="image") for i in range(40)]
        return DownloadGalleryOutput(url=url, files=files)

    result = await download_gallery(
        "https://example.com/album",
        max_items=99,
        backend=backend,
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert len(result.files) == 30
    assert result.truncated is True


@pytest.mark.asyncio
async def test_download_gallery_passes_netscape_cookiefile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COOKIES_DIR", str(tmp_path))
    from backend.skills.cookies import CookieJar

    jar = CookieJar(root=tmp_path)
    jar.save_storage_state(
        "bili",
        {
            "cookies": [
                {"name": "DedeUserID", "value": "1", "domain": ".bilibili.com", "path": "/"},
                {"name": "SESSDATA", "value": "s", "domain": ".bilibili.com", "path": "/"},
            ],
            "origins": [],
        },
    )
    seen: dict[str, Path | None] = {}

    async def backend(url: str, **kwargs) -> DownloadGalleryOutput:
        seen["cookiefile"] = kwargs.get("cookiefile")
        return DownloadGalleryOutput(url=url, files=[])

    result = await download_gallery(
        "https://www.bilibili.com/album/1",
        backend=backend,
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.error is None
    assert seen["cookiefile"] == jar.netscape_path("bili")
    assert seen["cookiefile"].is_file()
