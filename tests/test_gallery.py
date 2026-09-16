from __future__ import annotations

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
