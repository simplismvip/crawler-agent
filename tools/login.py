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
    cookie_value,
    has_login_sentinels,
    xhs_session_changed,
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
    *,
    verified_login: bool = False,
) -> Path:
    return jar.save_storage_state(
        platform,
        {"cookies": cookies, "origins": origins, "verified_login": verified_login},
    )


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


def _clear_profile_locks(profile: Path) -> None:
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = profile / name
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


async def _launch_login_context(playwright, profile: Path):
    _clear_profile_locks(profile)
    kwargs = {
        "user_data_dir": str(profile),
        "headless": False,
        "no_viewport": True,
        "args": ["--disable-session-crashed-bubble", "--hide-crash-restore-bubble"],
    }
    try:
        return await playwright.chromium.launch_persistent_context(channel="chrome", **kwargs)
    except Exception:
        return await playwright.chromium.launch_persistent_context(**kwargs)


async def _playwright_login(platform: str, jar: CookieJar, timeout: int) -> Path:
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("需要 Playwright：uv pip install playwright && playwright install chromium") from exc

    from backend.settings import ROOT

    needed = " / ".join("+".join(group) for group in PLATFORM_SENTINELS[platform])
    profile = ROOT / "data" / "browser_profiles" / platform
    profile.mkdir(parents=True, exist_ok=True)
    home = PLATFORM_HOME[platform]
    async with async_playwright() as playwright:
        context = await _launch_login_context(playwright, profile)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(home, wait_until="domcontentloaded")
            print(
                f"请在弹出的窗口完成 {platform} 登录。"
                f"{'小红书会先发游客 web_session，必须等它在登录后发生变化才算成功。' if platform == 'xhs' else f'脚本在等待 {needed}。'}",
                flush=True,
            )
            deadline = time.monotonic() + timeout
            last_status = 0.0
            baseline_session = ""
            while time.monotonic() < deadline:
                try:
                    cookies = await context.cookies()
                except PlaywrightError as exc:
                    raise SystemExit(f"浏览器已关闭，未完成登录：{exc}") from exc
                logged_in = False
                if platform == "xhs":
                    current = cookie_value(cookies, "web_session")
                    if current and not baseline_session:
                        baseline_session = current
                        print(
                            f"已记录游客 web_session（{len(baseline_session)} 字符）。请扫码/登录，窗口会保持打开。",
                            flush=True,
                        )
                    logged_in = xhs_session_changed(baseline_session, cookies)
                else:
                    logged_in = has_login_sentinels(platform, cookies)
                if logged_in:
                    print("检测到登录态，正在导出…", flush=True)
                    origins = []
                    try:
                        state = await context.storage_state()
                        origins = list(state.get("origins") or [])
                    except Exception:
                        origins = []
                    path = try_export(platform, cookies, origins, jar, verified_login=True)
                    await context.close()
                    return path
                now = time.monotonic()
                if now - last_status >= 8:
                    names = sorted(
                        {str(item.get("name") or "") for item in cookies if item.get("name")}
                    )
                    waiting = "web_session 变化" if platform == "xhs" else needed
                    print(f"仍在等待 {waiting}。当前 Cookie 名：{', '.join(names) or '（空）'}", flush=True)
                    last_status = now
                await asyncio.sleep(1)
        finally:
            try:
                await context.close()
            except Exception:
                pass
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
