from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class SkillContext:
    request_id: str
    cancel_event: asyncio.Event | None = None
