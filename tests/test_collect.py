from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.skills.collect import clamp_max_items, collect_dataset, normalize_fields
from backend.skills.cookies import CookieJar
from backend.skills.models import CollectDatasetInput

PAGE1_URL = "https://example.com/api/list"
PAGE2_URL = "https://example.com/api/page2"


def _item(index: int) -> dict:
    return {
        "author": {"name": "A"},
        "content": f"item-{index}",
        "url": f"https://example.com/a/{index}",
    }


def _page(start: int, count: int, *, is_end: bool, next_url: str | None) -> str:
    return json.dumps(
        {
            "data": [_item(start + i) for i in range(count)],
            "paging": {"is_end": is_end, "next": next_url},
        },
        ensure_ascii=False,
    )


async def fake_fetch(url: str) -> tuple[int, str, str]:
    if url == PAGE1_URL:
        return 200, "application/json", _page(0, 20, is_end=False, next_url=PAGE2_URL)
    if url == PAGE2_URL:
        return 200, "application/json", _page(20, 26, is_end=True, next_url=None)
    raise AssertionError(f"unexpected url: {url}")


def resolver(*_a, **_k):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def test_collect_input_schema_has_no_request_id() -> None:
    props = CollectDatasetInput.model_json_schema()["properties"]
    assert "url" in props
    assert "fields" in props
    assert "request_id" not in props
    assert "cookie" not in props and "cookies" not in props


def test_normalize_fields_maps_chinese_aliases() -> None:
    assert normalize_fields(["正文", "作者"]) == ["content", "author"]
    assert normalize_fields(["回答", "答主"]) == ["content", "author"]


def test_normalize_fields_maps_extra_aliases() -> None:
    assert normalize_fields(["内容", "标题", "时间", "点赞"]) == [
        "content",
        "title",
        "published_at",
        "voteup_count",
    ]
    assert normalize_fields(["日期", "赞同"]) == ["published_at", "voteup_count"]


def test_normalize_fields_up_author_variants() -> None:
    assert normalize_fields(["UP 主", "up 主", "Up 主"]) == ["author"]


def test_normalize_fields_dedupes_content_aliases() -> None:
    assert normalize_fields(["正文", "内容"]) == ["content"]


def test_normalize_fields_slugs_unknown_fields() -> None:
    assert normalize_fields(["Foo Bar"]) == ["foo_bar"]


def test_normalize_fields_skips_blank_inputs() -> None:
    assert normalize_fields(["  ", "作者"]) == ["author"]


def test_clamp_max_items() -> None:
    assert clamp_max_items(0) == 1
    assert clamp_max_items(46) == 46
    assert clamp_max_items(999) == 200


@pytest.mark.asyncio
async def test_collect_two_json_pages_writes_46_items(tmp_path: Path) -> None:
    result = await collect_dataset(
        PAGE1_URL,
        fields=["作者", "正文"],
        max_items=50,
        dest_dir=tmp_path,
        fetch=fake_fetch,
        resolver=resolver,
    )
    assert result.error is None
    assert result.count == 46
    assert result.truncated is False
    assert result.fields == ["author", "content"]
    assert result.path.endswith("dataset.json")
    blob = json.dumps(result.model_dump(), ensure_ascii=False)
    assert "item-0" not in blob
    rows = json.loads(Path(result.path).read_text(encoding="utf-8"))
    assert len(rows) == 46
    assert rows[0]["author"]
    assert rows[0]["content"]
    assert "url" in rows[0]


@pytest.mark.asyncio
async def test_collect_respects_max_items_truncated(tmp_path: Path) -> None:
    result = await collect_dataset(
        PAGE1_URL,
        fields=["作者", "正文"],
        max_items=10,
        dest_dir=tmp_path,
        fetch=fake_fetch,
        resolver=resolver,
    )
    assert result.error is None
    assert result.count == 10
    assert result.truncated is True
    assert len(json.loads(Path(result.path).read_text(encoding="utf-8"))) == 10


@pytest.mark.asyncio
async def test_collect_unparseable_json_does_not_write(tmp_path: Path) -> None:
    async def fetch(_url: str) -> tuple[int, str, str]:
        return 200, "application/json", '{"error":"nope"}'

    result = await collect_dataset(
        PAGE1_URL,
        fields=["作者", "正文"],
        dest_dir=tmp_path,
        fetch=fetch,
        resolver=resolver,
    )
    assert result.error
    assert "无法抽取列表" in result.error
    assert not (tmp_path / "dataset.json").exists()


@pytest.mark.asyncio
async def test_collect_rejects_loopback() -> None:
    result = await collect_dataset("http://127.0.0.1/api", fields=["content"])
    assert result.error
    assert result.path == ""


@pytest.mark.asyncio
async def test_collect_rejects_csv_format(tmp_path: Path) -> None:
    async def boom(url: str):
        raise AssertionError("must not fetch")

    result = await collect_dataset(
        "https://example.com/api",
        fields=["content"],
        format="csv",
        dest_dir=tmp_path,
        fetch=boom,
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.error
    assert not (tmp_path / "dataset.json").exists()


@pytest.mark.asyncio
async def test_collect_login_wall_does_not_write(tmp_path: Path) -> None:
    async def fetch(url: str):
        return 200, "text/html", "<html><head><title>请登录</title></head><body>请先登录后查看完整内容</body></html>"

    result = await collect_dataset(
        PAGE1_URL,
        fields=["content"],
        dest_dir=tmp_path,
        fetch=fetch,
        resolver=resolver,
    )
    assert "登录" in (result.error or "")
    assert "需要登录" in (result.error or "")
    assert "tools.login" in (result.error or "")
    assert not (tmp_path / "dataset.json").exists()


@pytest.mark.asyncio
async def test_collect_unparseable_html_does_not_dump_body(tmp_path: Path) -> None:
    async def fetch(url: str):
        return 200, "text/html", "<html><body><p>hello unique-secret-body</p></body></html>"

    result = await collect_dataset(
        PAGE1_URL,
        fields=["content"],
        dest_dir=tmp_path,
        fetch=fetch,
        resolver=resolver,
    )
    assert "无法抽取列表" in (result.error or "")
    assert "unique-secret-body" not in json.dumps(result.model_dump(), ensure_ascii=False)
    assert not (tmp_path / "dataset.json").exists()


@pytest.mark.asyncio
async def test_collect_rejects_loopback_next_url(tmp_path: Path) -> None:
    fetched: list[str] = []

    async def fetch(url: str) -> tuple[int, str, str]:
        fetched.append(url)
        return 200, "application/json", _page(0, 2, is_end=False, next_url="http://127.0.0.1/secret")

    result = await collect_dataset(
        PAGE1_URL,
        fields=["content"],
        dest_dir=tmp_path,
        fetch=fetch,
        resolver=resolver,
    )
    assert result.error is None
    assert result.truncated is True
    assert all("127.0.0.1" not in item for item in fetched)
    out = tmp_path / "dataset.json"
    assert out.exists()
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert len(rows) == 2
    assert rows[0]["content"] == "item-0"
    assert rows[1]["content"] == "item-1"


ZHIHU_QUESTION_URL = "https://www.zhihu.com/question/2083005795185312347"
ZHIHU_ANSWERS_API = (
    "https://www.zhihu.com/api/v3/question/2083005795185312347/answers"
    "?limit=20&offset=0&order_by=default"
)


def test_rewrite_list_url_zhihu_question() -> None:
    from backend.skills.collect import rewrite_list_url

    assert rewrite_list_url("https://www.zhihu.com/question/2083005795185312347") == (
        "https://www.zhihu.com/api/v3/question/2083005795185312347/answers?limit=20&offset=0&order_by=default"
    )
    assert rewrite_list_url("https://example.com/api/list") == "https://example.com/api/list"


@pytest.mark.asyncio
async def test_collect_rewrites_zhihu_question_url(tmp_path: Path) -> None:
    async def fetch(url: str) -> tuple[int, str, str]:
        if url == ZHIHU_ANSWERS_API:
            return (
                200,
                "application/json",
                json.dumps(
                    {
                        "data": [
                            {
                                "id": 1,
                                "url": "https://www.zhihu.com/question/2083005795185312347/answer/1",
                                "author": {"name": "Alice"},
                                "excerpt": "hello-excerpt",
                                "content": "<p>full-body-secret</p>",
                            }
                        ],
                        "paging": {"is_end": True},
                    },
                    ensure_ascii=False,
                ),
            )
        raise AssertionError(f"unexpected url: {url}")

    jar = CookieJar(root=tmp_path)
    jar.save_storage_state(
        "zhihu",
        {
            "cookies": [{"name": "z_c0", "value": "abc", "domain": ".zhihu.com", "path": "/"}],
            "origins": [],
        },
    )
    result = await collect_dataset(
        ZHIHU_QUESTION_URL,
        fields=["作者", "正文"],
        dest_dir=tmp_path,
        fetch=fetch,
        cookie_jar=jar,
        resolver=resolver,
    )
    assert result.error is None
    assert result.count == 1
    rows = json.loads(Path(result.path).read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["author"] == "Alice"
    assert rows[0]["content"] == "<p>full-body-secret</p>"
    dump = json.dumps(result.model_dump(), ensure_ascii=False)
    assert "full-body-secret" not in dump
    assert "hello-excerpt" not in dump


@pytest.mark.asyncio
async def test_collect_zhihu_without_sentinels_does_not_fetch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COOKIES_DIR", str(tmp_path))

    async def boom(url: str):
        raise AssertionError("must not fetch")

    result = await collect_dataset(
        "https://www.zhihu.com/question/1",
        fields=["content"],
        dest_dir=tmp_path / "out",
        fetch=boom,
        cookie_jar=CookieJar(root=tmp_path),
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert "登录" in (result.error or "")
    assert "tools.login" in (result.error or "")
    assert not (tmp_path / "out" / "dataset.json").exists()


@pytest.mark.asyncio
async def test_collect_http_error_does_not_ask_for_cookie(tmp_path: Path) -> None:
    async def fetch(_url: str) -> tuple[int, str, str]:
        return 403, "application/json", json.dumps({"error": "forbidden"})

    result = await collect_dataset(
        PAGE1_URL,
        fields=["content"],
        dest_dir=tmp_path,
        fetch=fetch,
        resolver=resolver,
    )
    assert "403" in (result.error or "")
    assert "Cookie" in (result.error or "")
    assert not (tmp_path / "dataset.json").exists()


@pytest.mark.asyncio
async def test_collect_httpx_sends_jar_cookies(tmp_path: Path) -> None:
    jar = CookieJar(root=tmp_path)
    jar.save_storage_state(
        "zhihu",
        {
            "cookies": [{"name": "z_c0", "value": "abc", "domain": ".zhihu.com", "path": "/"}],
            "origins": [],
        },
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["cookie"] = request.headers.get("cookie", "")
        seen["accept"] = request.headers.get("accept", "")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "author": {"name": "A"},
                        "content": "c",
                        "url": "https://www.zhihu.com/a/1",
                    }
                ],
                "paging": {"is_end": True},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await collect_dataset(
            "https://www.zhihu.com/api/v3/question/1/answers",
            fields=["author", "content"],
            dest_dir=tmp_path / "out",
            client=client,
            cookie_jar=jar,
            resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
            rate_limit=False,
        )
    assert result.error is None
    assert result.count == 1
    assert "z_c0=abc" in seen.get("cookie", "")
    assert "application/json" in seen.get("accept", "")
    assert (tmp_path / "out" / "dataset.json").is_file()


def test_collect_skill_always_available() -> None:
    from backend.skills.collect import CollectSkill

    assert CollectSkill().available() is True
    assert CollectSkill.name == "collect_dataset"
    schema = CollectSkill.input_model.model_json_schema()["properties"]
    assert "request_id" not in schema


def test_collect_preview_is_count_and_path_not_bodies() -> None:
    from backend.agent.engine import _preview_from_output
    from backend.skills.models import CollectDatasetOutput

    out = CollectDatasetOutput(url="https://example.com", path="/tmp/dataset.json", count=46, fields=["author"])
    preview, err = _preview_from_output(out)
    assert err is None
    assert "46" in preview
    assert "/tmp/dataset.json" in preview
    assert "author-secret-body" not in preview

