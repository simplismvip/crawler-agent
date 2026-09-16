from __future__ import annotations

from typing import Any

from backend.skills.models import SearchWebInput, ScrapePageInput
from backend.skills.scraper import scrape_page
from backend.skills.search import search_web

TOOL_HANDLERS = {
    "search_web": search_web,
    "scrape_page": scrape_page,
}

_TOOL_MODELS = {
    "search_web": (SearchWebInput, "Search the public web and return title/url/snippet hits."),
    "scrape_page": (ScrapePageInput, "Fetch a public http(s) page and extract main content as Markdown."),
}


def openai_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for name, (model, description) in _TOOL_MODELS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema,
                },
            }
        )
    return tools
