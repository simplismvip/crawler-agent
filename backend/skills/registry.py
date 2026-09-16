from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from backend.agent.prompt import SYSTEM_PROMPT_HEADER
from backend.skills.base import SkillContext
from backend.skills.gallery import GallerySkill
from backend.skills.media import MediaSkill
from backend.skills.models import SkillInfo
from backend.skills.rendered import RenderedSkill
from backend.skills.scraper import ScrapePageSkill
from backend.skills.search import SearchWebSkill
from backend.skills.social import SocialSkill


_EXTRAS_META = {
    "rendered": ("crawl4ai", "uv pip install crawl4ai"),
    "media": ("yt-dlp", "uv pip install yt-dlp"),
    "gallery": ("gallery-dl", "uv pip install gallery-dl"),
    "http-stealth": ("curl_cffi", "uv pip install curl_cffi"),
    "social": (None, None),
}


def builtin_skills() -> list[Any]:
    return [
        SearchWebSkill(),
        ScrapePageSkill(),
        RenderedSkill(),
        MediaSkill(),
        GallerySkill(),
        SocialSkill(),
    ]


class SkillRegistry:
    def __init__(self, skills: list[Any] | None = None) -> None:
        self._skills = list(skills if skills is not None else builtin_skills())

    def all_declared(self) -> list[Any]:
        return list(self._skills)

    def enabled(self) -> list[Any]:
        return [skill for skill in self._skills if skill.available()]

    def get(self, name: str) -> Any | None:
        for skill in self.enabled():
            if skill.name == name:
                return skill
        return None

    def openai_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for skill in self.enabled():
            schema = skill.input_model.model_json_schema()
            schema.pop("title", None)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": skill.name,
                        "description": skill.description,
                        "parameters": schema,
                    },
                }
            )
        return tools

    def build_system_prompt(self) -> str:
        parts = [SYSTEM_PROMPT_HEADER.strip()]
        for skill in self.enabled():
            routing = getattr(skill, "routing", "") or ""
            if routing.strip():
                parts.append(routing.strip())
        return "\n".join(parts) + "\n"

    def skill_infos(self) -> list[SkillInfo]:
        infos: list[SkillInfo] = []
        for skill in self.all_declared():
            available = skill.available()
            extra = getattr(skill, "extras", None)
            missing, install = _EXTRAS_META.get(extra or "", (None, None))
            reason = None
            if not available:
                if extra == "social":
                    reason = "MediaCrawler not installed (set MEDIACRAWLER_HOME)"
                elif missing:
                    reason = f"missing extras ({missing})"
                else:
                    reason = "unavailable"
            infos.append(
                SkillInfo(
                    name=skill.name,
                    description=skill.description,
                    available=available,
                    extras=extra,
                    missing_dependency=None if available else missing,
                    install_cmd=None if available else install,
                    unavailable_reason=reason,
                )
            )
        return infos


default_registry = SkillRegistry()


def openai_tools() -> list[dict[str, Any]]:
    return default_registry.openai_tools()


class SkillErrorOutput(BaseModel):
    error: str


async def run_skill(name: str, args: dict[str, Any], context: SkillContext) -> BaseModel:
    skill = default_registry.get(name)
    if skill is None:
        return SkillErrorOutput(error="unknown skill")
    return await skill.run(args, context)
