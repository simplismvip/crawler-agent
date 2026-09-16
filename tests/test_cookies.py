from __future__ import annotations

from pathlib import Path

from backend.skills.cookies import (
    CookieJar,
    cookies_json_to_netscape,
    detect_login_wall,
    has_login_sentinels,
    infer_platform,
    is_logged_in,
)


def test_infer_platform_from_host() -> None:
    assert infer_platform("https://www.xiaohongshu.com/explore/abc") == "xhs"
    assert infer_platform("https://www.bilibili.com/video/BV1xx") == "bili"
    assert infer_platform("https://www.zhihu.com/question/1") == "zhihu"
    assert infer_platform("https://www.douyin.com/video/1") == "dy"
    assert infer_platform("https://weibo.com/ttarticle/p/show?id=1") == "wb"
    assert infer_platform("https://example.com/") is None


def test_xhs_sentinel_requires_web_session_not_guest_a1() -> None:
    assert has_login_sentinels("xhs", [{"name": "web_session", "value": "x"}])
    assert not has_login_sentinels("xhs", [{"name": "a1", "value": "y"}])
    assert not has_login_sentinels("xhs", [{"name": "guest", "value": "1"}])
    assert not has_login_sentinels("xhs", [{"name": "web_session", "value": ""}])
    assert not has_login_sentinels("xhs", [{"name": "web_session", "value": "   "}])
    assert has_login_sentinels(
        "xhs",
        [{"name": "a1", "value": "y"}, {"name": "web_session", "value": "x"}],
    )
    guest_state = {
        "cookies": [{"name": "web_session", "value": "0300guest", "domain": ".xiaohongshu.com", "path": "/"}],
        "origins": [],
    }
    assert not is_logged_in("xhs", guest_state)
    guest_state["verified_login"] = True
    assert is_logged_in("xhs", guest_state)


def test_bili_sentinel_requires_both_keys() -> None:
    assert not has_login_sentinels("bili", [{"name": "DedeUserID", "value": "1"}])
    assert has_login_sentinels(
        "bili",
        [{"name": "DedeUserID", "value": "1"}, {"name": "SESSDATA", "value": "s"}],
    )


def test_netscape_httponly_and_integer_expires() -> None:
    text = cookies_json_to_netscape(
        [
            {
                "name": "SESSDATA",
                "value": "secret",
                "domain": ".bilibili.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "expires": 1735689600.7,
            }
        ]
    )
    assert text.startswith("# Netscape HTTP Cookie File")
    assert "\t" in text
    assert "#HttpOnly_.bilibili.com" in text
    assert "1735689600.7" not in text
    assert "1735689600" in text
    assert "SESSDATA" in text
    assert "sameSite" not in text


def test_netscape_empty_still_has_header() -> None:
    text = cookies_json_to_netscape([])
    assert text.startswith("# Netscape HTTP Cookie File")


def test_login_wall_by_url_and_title_and_phrase() -> None:
    assert detect_login_wall(
        url="https://www.zhihu.com/login?next=/",
        title="知乎",
        html="<html><body>ok</body></html>",
    )
    assert detect_login_wall(
        url="https://www.zhihu.com/question/1",
        title="请登录 - 知乎",
        html="<html><body>hello</body></html>",
    )
    assert detect_login_wall(
        url="https://blog.example.com/post",
        title="文章",
        html="<html><body>请先登录后查看完整内容</body></html>",
    )


def test_footer_login_link_is_not_login_wall() -> None:
    html = """
    <html><head><title>公开文章</title></head>
    <body>
      <p>这是一篇完整的公开正文，足够长，不需要账号也能阅读。</p>
      <footer><a href="/login">登录</a></footer>
    </body></html>
    """
    assert not detect_login_wall(
        url="https://example.com/post",
        title="公开文章",
        html=html,
    )


def test_cookie_jar_loads_storage_state_for_host(tmp_path: Path) -> None:
    jar = CookieJar(root=tmp_path)
    jar.save_storage_state(
        "bili",
        {
            "cookies": [
                {
                    "name": "DedeUserID",
                    "value": "42",
                    "domain": ".bilibili.com",
                    "path": "/",
                },
                {
                    "name": "SESSDATA",
                    "value": "tok",
                    "domain": ".bilibili.com",
                    "path": "/",
                },
            ],
            "origins": [],
        },
    )
    cookies = jar.cookies_for_url("https://www.bilibili.com/video/BV1")
    names = {item["name"] for item in cookies}
    assert names == {"DedeUserID", "SESSDATA"}
    netscape = (tmp_path / "bili.netscape.txt").read_text(encoding="utf-8")
    assert "SESSDATA" in netscape
    assert jar.netscape_for_url("https://www.bilibili.com/video/BV1") == jar.netscape_path("bili")
    assert jar.netscape_for_url("https://example.com/") is None
    state = jar.storage_state_for_url("https://www.bilibili.com/video/BV1")
    assert state is not None
    names = {item["name"] for item in state["cookies"]}
    assert names == {"DedeUserID", "SESSDATA"}
    assert jar.storage_state_for_url("https://example.com/") is None


def test_cookie_jar_refuses_guest_export(tmp_path: Path) -> None:
    jar = CookieJar(root=tmp_path)
    try:
        jar.save_storage_state("xhs", {"cookies": [{"name": "guest", "value": "1"}], "origins": []})
    except ValueError as exc:
        assert "登录" in str(exc) or "sentinel" in str(exc).lower() or "特征" in str(exc)
    else:
        raise AssertionError("guest cookies must not be saved")
    assert not (tmp_path / "xhs.json").exists()
