from __future__ import annotations

from pydantic import BaseModel

from backend.skills.base import SkillContext
from backend.skills.models import ScrapePageInput
from backend.skills.registry import SkillRegistry, default_registry


class _DisabledSkill:
    name = "scrape_rendered"
    description = "Render a JS page."
    input_model = ScrapePageInput
    extras = "rendered"
    routing = "JS 页用 scrape_rendered。"

    def available(self) -> bool:
        return False

    async def run(self, args: dict, context: SkillContext) -> BaseModel:
        raise AssertionError("disabled skill must not run")


def test_default_registry_always_includes_search_and_scrape() -> None:
    names = [item["function"]["name"] for item in default_registry.openai_tools()]
    assert names[0:2] == ["search_web", "scrape_page"]
    assert "collect_dataset" in names
    for extra in ("scrape_rendered", "download_media", "download_gallery"):
        if default_registry.get(extra):
            assert extra in names
        else:
            assert extra not in names


def test_scrape_input_schema_has_no_request_id() -> None:
    schema = ScrapePageInput.model_json_schema()
    assert "request_id" not in schema.get("properties", {})
    scrape = next(
        item for item in default_registry.openai_tools() if item["function"]["name"] == "scrape_page"
    )
    assert "request_id" not in scrape["function"]["parameters"].get("properties", {})


def test_unavailable_skill_is_omitted_from_tools() -> None:
    from backend.skills.search import SearchWebSkill

    registry = SkillRegistry([SearchWebSkill(), _DisabledSkill()])
    names = [item["function"]["name"] for item in registry.openai_tools()]
    assert names == ["search_web"]
    assert registry.get("scrape_rendered") is None


def test_system_prompt_includes_hint_rule_and_enabled_routing() -> None:
    prompt = default_registry.build_system_prompt()
    assert "hint" in prompt
    assert "严禁把 hint" in prompt or "禁止把 hint" in prompt
    assert "search_web" in prompt
    assert "scrape_page" in prompt
    assert "tools.login" in prompt
    assert "zhihu=" in prompt
    assert "自动" in prompt
    assert "禁止" in prompt
    assert "curl" in prompt
    assert "collect_dataset" in prompt
    assert "截断" in prompt
    assert "不限网站" in prompt
    collect = next(
        item for item in default_registry.openai_tools() if item["function"]["name"] == "collect_dataset"
    )
    assert "any site" in collect["function"]["description"].lower()
    scrape = next(
        item for item in default_registry.openai_tools() if item["function"]["name"] == "scrape_page"
    )
    assert "Cookie" in scrape["function"]["description"] or "cookie" in scrape["function"]["description"].lower() or "登录" in scrape["function"]["description"]
    if default_registry.get("scrape_rendered"):
        assert "scrape_rendered" in prompt
    if default_registry.get("download_media"):
        assert "禁止建议" in prompt
        assert "yt-dlp" in prompt
        assert "info_only=false" in prompt
        assert "Connection error" in prompt


def test_skill_infos_include_install_hints_for_extras() -> None:
    names = [item.name for item in default_registry.skill_infos()]
    assert names == [
        "search_web",
        "scrape_page",
        "collect_dataset",
        "scrape_rendered",
        "download_media",
        "download_gallery",
        "scrape_social",
    ]
    rendered = next(item for item in default_registry.skill_infos() if item.name == "scrape_rendered")
    if not rendered.available:
        assert rendered.missing_dependency == "crawl4ai"
        assert rendered.install_cmd == "uv pip install crawl4ai"
        assert rendered.unavailable_reason



def test_skill_infos_include_install_hints_for_missing_extras() -> None:
    infos = {item.name: item for item in default_registry.skill_infos()}
    assert infos["search_web"].available is True
    rendered = infos["scrape_rendered"]
    if not rendered.available:
        assert rendered.missing_dependency == "crawl4ai"
        assert rendered.install_cmd == "uv pip install crawl4ai"
    media = infos["download_media"]
    if not media.available:
        assert media.missing_dependency == "yt-dlp"
    social = infos["scrape_social"]
    assert social.available is False
    assert social.unavailable_reason

