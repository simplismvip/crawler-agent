from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.models import ScrapeSocialOutput
from backend.skills.registry import default_registry
from backend.skills.social import SocialSkill, scrape_social


def test_social_hidden_without_mediacrawler() -> None:
    assert default_registry.get("scrape_social") is None
    assert SocialSkill().available() is False


@pytest.mark.asyncio
async def test_scrape_social_without_cookies_explains_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOCIAL_COOKIES_DIR", str(tmp_path))

    class Adapter:
        def installed(self) -> bool:
            return True

        async def scrape(self, url: str, platform: str, cookie_path: Path | None) -> ScrapeSocialOutput:
            raise AssertionError("must not scrape without cookies")

    result = await scrape_social(
        "https://www.xiaohongshu.com/explore/abc",
        adapter=Adapter(),
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.platform == "xhs"
    assert result.error
    assert "登录" in result.error or "Cookie" in result.error
