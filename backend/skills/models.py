from __future__ import annotations

from pydantic import BaseModel, Field


class SearchWebInput(BaseModel):
    query: str
    max_results: int = Field(default=3, ge=1, le=5)


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""


class SearchWebOutput(BaseModel):
    query: str
    results: list[SearchHit] = Field(default_factory=list)
    error: str | None = None


class ScrapePageInput(BaseModel):
    url: str


class ScrapePageOutput(BaseModel):
    url: str
    title: str = ""
    markdown: str = ""
    truncated: bool = False
    error: str | None = None
    hint: str | None = None


class ScrapeRenderedInput(BaseModel):
    url: str


class ScrapeRenderedOutput(BaseModel):
    url: str
    title: str = ""
    markdown: str = ""
    truncated: bool = False
    error: str | None = None
    hint: str | None = None


class DownloadMediaInput(BaseModel):
    url: str
    audio_only: bool = False
    info_only: bool = True


class MediaFile(BaseModel):
    path: str
    media_type: str = ""
    bytes: int = 0


class DownloadMediaOutput(BaseModel):
    url: str
    title: str = ""
    extractor: str = ""
    duration: float | None = None
    uploader: str = ""
    description: str = ""
    captions: str = ""
    files: list[MediaFile] = Field(default_factory=list)
    error: str | None = None


class DownloadGalleryInput(BaseModel):
    url: str
    max_items: int = Field(default=12, ge=1, le=30)


class DownloadGalleryOutput(BaseModel):
    url: str
    title: str = ""
    files: list[MediaFile] = Field(default_factory=list)
    truncated: bool = False
    error: str | None = None


class ScrapeSocialInput(BaseModel):
    url: str
    platform: str | None = None


class ScrapeSocialOutput(BaseModel):
    url: str
    platform: str = ""
    markdown: str = ""
    truncated: bool = False
    error: str | None = None
    hint: str | None = None


class SkillInfo(BaseModel):
    name: str
    description: str
    available: bool
    extras: str | None = None
    missing_dependency: str | None = None
    install_cmd: str | None = None
    unavailable_reason: str | None = None

