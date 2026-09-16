from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.skills.cookies import (
    PLATFORM_SENTINELS,
    CookieJar,
    has_login_sentinels,
)

PLATFORM_HOME = {
    "xhs": "https://www.xiaohongshu.com",
    "bili": "https://www.bilibili.com",
    "zhihu": "https://www.zhihu.com",
    "dy": "https://www.douyin.com",
    "wb": "https://weibo.com",
}


def try_export(
    platform: str,
    cookies: list[dict[str, Any]],
    origins: list[dict[str, Any]],
    jar: CookieJar,
) -> Path:
    return jar.save_storage_state(platform, {"cookies": cookies, "origins": origins})


def poll_cookies(
    platform: str,
    fetch_cookies: Callable[[], list[dict[str, Any]]],
    *,
    timeout: float = 300,
    interval: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    on_tick: Callable[[], None] | None = None,
) -> list[dict[str, Any]] | None:
    deadline = clock() + timeout
    while clock() < deadline:
        cookies = fetch_cookies()
        if has_login_sentinels(platform, cookies):
            return cookies
        if on_tick:
            on_tick()
        sleeper(interval)
    cookies = fetch_cookies()
    if has_login_sentinels(platform, cookies):
        return cookies
    return None


async def _playwright_login(platform: str, jar: CookieJar, timeout: int) -> Path:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("需要 Playwright：uv pip install playwright && playwright install chromium") from exc

    from backend.settings import ROOT

    profile = ROOT / "data" / "browser_profiles" / platform
    profile.mkdir(parents=True, exist_ok=True)
    home = PLATFORM_HOME[platform]
    async with async_playwright() as playwright:
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
                channel="chrome",
            )
        except Exception:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
            )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(home, wait_until="domcontentloaded")
        print(f"请在弹出的窗口完成 {platform} 登录。脚本按关键 Cookie 轮询，未检测到登录态不会写出文件。", flush=True)
        deadline = time.monotonic() + timeout
        cookies: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            cookies = await context.cookies()
            if has_login_sentinels(platform, cookies):
                print("检测到登录态，正在导出…", flush=True)
                origins = []
                try:
                    state = await context.storage_state()
                    origins = list(state.get("origins") or [])
                except Exception:
                    origins = []
                path = try_export(platform, cookies, origins, jar)
                await context.close()
                return path
            await asyncio.sleep(1)
        await context.close()
    raise SystemExit("未检测到有效登录特征，没有写出游客 Cookie。请重试。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="在专用浏览器窗口登录，并把会话写入 data/cookies/")
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORM_SENTINELS))
    parser.add_argument("--cookies-dir", default=None)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    jar = CookieJar(root=Path(args.cookies_dir) if args.cookies_dir else None)
    path = asyncio.run(_playwright_login(args.platform, jar, args.timeout))
    print(f"已导出 {path} 与 {jar.netscape_path(args.platform)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
