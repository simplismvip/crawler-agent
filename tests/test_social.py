from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.skills.models import ScrapeSocialOutput
from backend.skills.registry import default_registry
from backend.skills.social import (
    EnvAdapter,
    SocialSkill,
    build_mediacrawler_args,
    infer_platform,
    public_mc_error,
    records_to_markdown,
    scrape_social,
    social_url_error,
)

XHS_NOTE = (
    "https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8"
    "?xsec_token=AB3rO-QopW5sgrJ41GwN01WCXh6yWPxjSoFI9D5JIMgKw="
)
XHS_PROFILE = (
    "https://www.xiaohongshu.com/user/profile/5ffe4a8c000000000100a3d9"
    "?xsec_token=ABzFG-qcykZc_vPYXfR8fGgXN5F6eTyEem8cC__6D94UI="
    "&xsec_source=pc_feed"
)


def test_social_hidden_without_mediacrawler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEDIACRAWLER_HOME", raising=False)
    monkeypatch.setattr("backend.skills.social.mediacrawler_home", lambda: None)
    assert SocialSkill().available() is False
    assert default_registry.get("scrape_social") is None


def test_infer_platform_includes_zhihu() -> None:
    assert infer_platform("https://www.zhihu.com/question/1", None) == "zhihu"
    assert infer_platform("https://www.xiaohongshu.com/explore/abc", None) == "xhs"


def test_social_url_error_rejects_xhs_explore_homepage() -> None:
    err = social_url_error("xhs", "https://www.xiaohongshu.com/explore")
    assert err
    assert "笔记" in err
    assert "collect_dataset" in err
    assert social_url_error("xhs", XHS_NOTE) is None
    assert social_url_error("xhs", XHS_PROFILE) is None
    assert social_url_error("zhihu", "https://www.zhihu.com/question/1") is None


def test_public_mc_error_maps_playwright_and_redacts_cookies() -> None:
    msg = public_mc_error(
        "BrowserType.launch_persistent_context: Executable doesn't exist. Please run playwright install",
        1,
    )
    assert "Playwright" in msg
    assert "不是没登录" in msg
    assert "collect_dataset" in msg
    leaked = public_mc_error("failed --cookies web_session=SECRET123 a1=fingerprint", 1)
    assert "SECRET123" not in leaked
    assert "不是没登录" in leaked
    fetch = public_mc_error(
        'tenacity.RetryError: RetryError[<Future at 0x1 state=finished raised DataFetchError>]',
        1,
    )
    assert "DataFetchError" in fetch
    assert "不是 URL 不支持" in fetch
    assert "collect_dataset" in fetch


def test_records_to_markdown_uses_common_fields() -> None:
    markdown = records_to_markdown(
        [
            {
                "title": "笔记标题",
                "nickname": "作者A",
                "desc": "正文一段",
                "note_url": "https://www.xiaohongshu.com/explore/abc",
            }
        ]
    )
    assert "笔记标题" in markdown
    assert "作者A" in markdown
    assert "正文一段" in markdown


def test_build_mediacrawler_args_is_detail_cookie_login() -> None:
    args = build_mediacrawler_args(
        platform="zhihu",
        url="https://www.zhihu.com/question/1",
        cookies="z_c0=abc",
        save_path="/tmp/out",
    )
    assert "--platform" in args and "zhihu" in args
    assert "--lt" in args and "cookie" in args
    assert "--type" in args
    assert "detail" in args
    assert "--specified_id" in args
    assert "https://www.zhihu.com/question/1" in args
    assert "--save_data_option" in args and "json" in args
    assert "--get_comment" in args
    assert args[args.index("--cookies") + 1] == "z_c0=abc"
    assert "--creator_id" not in args


def test_build_mediacrawler_args_uses_creator_mode_for_xhs_profile() -> None:
    args = build_mediacrawler_args(
        platform="xhs",
        url=XHS_PROFILE,
        cookies="web_session=ok",
        save_path="/tmp/out",
    )
    assert args[args.index("--type") + 1] == "creator"
    assert args[args.index("--creator_id") + 1] == XHS_PROFILE
    assert "--specified_id" not in args


@pytest.mark.asyncio
async def test_scrape_social_without_cookies_explains_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOCIAL_COOKIES_DIR", str(tmp_path))

    class Adapter:
        def installed(self) -> bool:
            return True

        async def scrape(self, url: str, platform: str, cookie_path: Path | None) -> ScrapeSocialOutput:
            raise AssertionError("must not scrape without cookies")

    result = await scrape_social(
        XHS_NOTE,
        adapter=Adapter(),
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.platform == "xhs"
    assert result.error
    assert "登录" in result.error or "Cookie" in result.error or "tools.login" in result.error


@pytest.mark.asyncio
async def test_xhs_explore_homepage_does_not_call_adapter() -> None:
    class Adapter:
        def installed(self) -> bool:
            return True

        async def scrape(self, url: str, platform: str, cookie_path: Path | None) -> ScrapeSocialOutput:
            raise AssertionError("homepage is not a note URL")

    result = await scrape_social(
        "https://www.xiaohongshu.com/explore",
        adapter=Adapter(),
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.platform == "xhs"
    assert result.error
    assert "笔记" in result.error
    assert "collect_dataset" in result.error


@pytest.mark.asyncio
async def test_scrape_social_with_sentinels_calls_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOCIAL_COOKIES_DIR", str(tmp_path))
    monkeypatch.setenv("COOKIES_DIR", str(tmp_path))
    from backend.skills.cookies import CookieJar

    CookieJar(root=tmp_path).save_storage_state(
        "xhs",
        {
            "cookies": [
                {"name": "web_session", "value": "ok", "domain": ".xiaohongshu.com", "path": "/"}
            ],
            "origins": [],
            "verified_login": True,
        },
    )

    class Adapter:
        def installed(self) -> bool:
            return True

        async def scrape(self, url: str, platform: str, cookie_path: Path | None) -> ScrapeSocialOutput:
            assert platform == "xhs"
            assert cookie_path is not None
            return ScrapeSocialOutput(url=url, platform=platform, markdown="笔记正文")

    result = await scrape_social(
        XHS_NOTE,
        adapter=Adapter(),
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.markdown.startswith("笔记")
    assert result.error is None


@pytest.mark.asyncio
async def test_env_adapter_reads_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIACRAWLER_HOME", str(tmp_path / "mc"))
    monkeypatch.setenv("COOKIES_DIR", str(tmp_path))
    (tmp_path / "mc").mkdir()
    (tmp_path / "mc" / "main.py").write_text("# stub\n", encoding="utf-8")
    from backend.skills.cookies import CookieJar

    cookie_path = CookieJar(root=tmp_path).save_storage_state(
        "xhs",
        {
            "cookies": [
                {"name": "web_session", "value": "ok", "domain": ".xiaohongshu.com", "path": "/"}
            ],
            "origins": [],
            "verified_login": True,
        },
    )

    async def fake_run(argv: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
        assert "--lt" in argv and "cookie" in argv
        save = Path(argv[argv.index("--save_data_path") + 1])
        dest = save / "xhs" / "json"
        dest.mkdir(parents=True)
        (dest / "detail_contents.json").write_text(
            json.dumps([{"title": "from-mc", "desc": "hello note", "nickname": "n"}], ensure_ascii=False),
            encoding="utf-8",
        )
        return 0, ""

    adapter = EnvAdapter(runner=fake_run)
    result = await adapter.scrape(
        "https://www.xiaohongshu.com/explore/abc",
        "xhs",
        cookie_path,
    )
    assert result.error is None
    assert "from-mc" in result.markdown
    assert "hello note" in result.markdown


@pytest.mark.asyncio
async def test_env_adapter_surfaces_playwright_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIACRAWLER_HOME", str(tmp_path / "mc"))
    monkeypatch.setenv("COOKIES_DIR", str(tmp_path))
    (tmp_path / "mc").mkdir()
    (tmp_path / "mc" / "main.py").write_text("# stub\n", encoding="utf-8")
    from backend.skills.cookies import CookieJar

    cookie_path = CookieJar(root=tmp_path).save_storage_state(
        "xhs",
        {
            "cookies": [
                {"name": "web_session", "value": "ok", "domain": ".xiaohongshu.com", "path": "/"}
            ],
            "origins": [],
            "verified_login": True,
        },
    )

    async def fake_run(argv: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
        return 1, "Executable doesn't exist at chrome-headless-shell. Please run playwright install"

    adapter = EnvAdapter(runner=fake_run)
    result = await adapter.scrape(XHS_NOTE, "xhs", cookie_path)
    assert result.markdown is None or result.markdown == ""
    assert result.error
    assert "Playwright" in result.error
    assert "不是没登录" in result.error
    assert "collect_dataset" in result.error
