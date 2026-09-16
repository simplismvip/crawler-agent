from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

from backend.skills.base import SkillContext
from backend.skills.models import ScrapePageInput
from backend.skills.registry import SkillRegistry
from backend.skills.rendered import RenderedSkill, scrape_rendered
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
