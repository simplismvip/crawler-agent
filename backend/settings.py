from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv()


def _normalize_openai_base(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url:
        return "https://api.openai.com/v1"
    host = (urlparse(url).hostname or "").lower()
    if "minimax" in host and not url.endswith("/v1"):
        return f"{url}/v1"
    return url


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    search_api_key: str
    searxng_base_url: str
    api_token: str
    host: str
    port: int
    sqlite_path: Path

    @property
    def is_minimax(self) -> bool:
        return "minimax" in self.openai_base_url.lower() or self.openai_model.lower().startswith("minimax")

    @classmethod
    def load(cls) -> "Settings":
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY") or ""
        raw_base = os.getenv("OPENAI_BASE_URL") or os.getenv("MINIMAX_BASE_URL") or "https://api.openai.com/v1"
        base = _normalize_openai_base(raw_base)
        default_model = "MiniMax-M3" if "minimax" in base.lower() else "gpt-4o-mini"
        return cls(
            openai_api_key=api_key,
            openai_base_url=base,
            openai_model=os.getenv("OPENAI_MODEL") or default_model,
            search_api_key=os.getenv("SEARCH_API_KEY", ""),
            searxng_base_url=(os.getenv("SEARXNG_BASE_URL") or "").strip().rstrip("/"),
            api_token=os.getenv("API_TOKEN", ""),
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8000")),
            sqlite_path=Path(os.getenv("SQLITE_PATH") or ROOT / "data" / "crawler-agent.db"),
        )


settings = Settings.load()
