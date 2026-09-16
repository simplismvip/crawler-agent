from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.cookies import CookieJar
from tools.login import poll_cookies, try_export


def test_try_export_rejects_guest_cookies(tmp_path: Path) -> None:
    jar = CookieJar(root=tmp_path)
    with pytest.raises(ValueError):
        try_export("xhs", [{"name": "guest", "value": "1"}], [], jar)
    assert not (tmp_path / "xhs.json").exists()


def test_try_export_writes_storage_state(tmp_path: Path) -> None:
    jar = CookieJar(root=tmp_path)
    path = try_export(
        "xhs",
        [{"name": "web_session", "value": "ok", "domain": ".xiaohongshu.com", "path": "/"}],
        [],
        jar,
    )
    assert path.is_file()
    assert "web_session" in path.read_text(encoding="utf-8")
    assert jar.netscape_path("xhs").is_file()


def test_try_export_does_not_overwrite_valid_file_on_guest(tmp_path: Path) -> None:
    jar = CookieJar(root=tmp_path)
    try_export(
        "xhs",
        [{"name": "web_session", "value": "keep-me", "domain": ".xiaohongshu.com", "path": "/"}],
        [],
        jar,
    )
    original = (tmp_path / "xhs.json").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        try_export("xhs", [{"name": "guest", "value": "1"}], [], jar)
    assert (tmp_path / "xhs.json").read_text(encoding="utf-8") == original
    assert "keep-me" in original


def test_poll_cookies_waits_until_sentinel() -> None:
    calls = {"n": 0}

    def fetch() -> list[dict]:
        calls["n"] += 1
        if calls["n"] < 3:
            return [{"name": "guest", "value": "1"}]
        return [{"name": "a1", "value": "ok"}]

    sleeps: list[float] = []
    result = poll_cookies(
        "xhs",
        fetch,
        timeout=10,
        interval=0.01,
        clock=lambda: 0 if calls["n"] < 5 else 100,
        sleeper=sleeps.append,
    )
    assert result is not None
    assert any(item["name"] == "a1" for item in result)
    assert sleeps
