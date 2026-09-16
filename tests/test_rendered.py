from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

from backend.skills.base import SkillContext
from backend.skills.models import ScrapePageInput
from backend.skills.registry import SkillRegistry
from backend.skills.rendered import RenderedSkill, markdown_from_crawl_result, scrape_rendered
from backend.skills.search import SearchWebSkill


class _FakeRendered:
    name = "scrape_rendered"
    description = "Render JS pages."
    input_model = ScrapePageInput
    extras = "rendered"
    routing = "JS 页在 scrape_page 失败后用 scrape_rendered。"

    def available(self) -> bool:
        return True

    async def run(self, args: dict, context: SkillContext) -> BaseModel:
        raise AssertionError("not used")


def test_rendered_skill_hidden_when_crawl4ai_missing() -> None:
    skill = RenderedSkill()
    if skill.available():
        pytest.skip("crawl4ai is installed in this environment")
    registry = SkillRegistry([SearchWebSkill(), skill])
    names = [item["function"]["name"] for item in registry.openai_tools()]
    assert "scrape_rendered" not in names
    prompt = registry.build_system_prompt()
    assert "scrape_rendered" not in prompt


def test_rendered_skill_appears_when_marked_available() -> None:
    registry = SkillRegistry([SearchWebSkill(), _FakeRendered()])
    names = [item["function"]["name"] for item in registry.openai_tools()]
    assert names == ["search_web", "scrape_rendered"]
    assert "scrape_rendered" in registry.build_system_prompt()


@pytest.mark.asyncio
async def test_scrape_rendered_uses_injected_crawler_and_validates_ssrf() -> None:
    async def crawler(url: str) -> str:
        assert url == "https://example.com/app"
        return "# Hello from render\n\nEnough text for a rendered article body that should survive truncation heuristics and be returned as markdown."

    result = await scrape_rendered(
        "https://example.com/app",
        crawler=crawler,
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.error is None
    assert "Hello from render" in result.markdown


@pytest.mark.asyncio
async def test_scrape_rendered_rejects_loopback() -> None:
    async def crawler(_url: str) -> str:
        raise AssertionError("must not crawl")

    result = await scrape_rendered("http://127.0.0.1/secret", crawler=crawler)
    assert result.error
    assert "not allowed" in result.error or "ip" in result.error


def test_rendered_uses_storage_state_when_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COOKIES_DIR", str(tmp_path))
    from backend.skills.cookies import CookieJar
    from backend.skills.rendered import storage_state_for_render

    jar = CookieJar(root=tmp_path)
    jar.save_storage_state(
        "zhihu",
        {"cookies": [{"name": "z_c0", "value": "tok", "domain": ".zhihu.com", "path": "/"}], "origins": []},
    )
    state = storage_state_for_render("https://www.zhihu.com/question/1", jar=jar)
    assert state is not None
    assert any(item["name"] == "z_c0" for item in state["cookies"])
    assert storage_state_for_render("https://example.com/", jar=jar) is None


class _CrawlResult:
    def __init__(self, *, success: bool, markdown: str = "", error_message: str = "", status_code: int | None = 200):
        self.success = success
        self.markdown = markdown
        self.error_message = error_message
        self.status_code = status_code


def test_blocked_crawl_result_is_error_not_fake_markdown() -> None:
    markdown, error = markdown_from_crawl_result(
        _CrawlResult(
            success=False,
            markdown="![ZhiHu logo](https://static.zhihu.com/logo.png)",
            error_message="Blocked by anti-bot protection: HTTP 403",
            status_code=403,
        )
    )
    assert markdown == ""
    assert error
    assert "403" in error or "Blocked" in error
