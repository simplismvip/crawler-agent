# Collect Dataset Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `collect_dataset` so large list scrapes write one `dataset.json` under `data/downloads/{request_id}/` and the chat only gets path + count.

**Architecture:** A always-on Skill paginates JSON APIs (Zhihu answers as the acceptance path) with CookieJar + SSRF, projects user fields, and never returns item bodies to the model. `scrape_page` stays single-page; when content would overflow chat, the prompt tells the model to offer this Skill instead of dumping truncated markdown.

**Tech Stack:** Python 3.12, httpx, pydantic, pytest, existing CookieJar / `sandbox_download_dir`.

**Spec:** `docs/superpowers/specs/2026-09-16-collect-dataset-design.md`

## Global Constraints

- Cookie values never appear in tool output, preview, logs, or `dataset.json` field values copied from headers (only page payload fields).
- No Cookie parameter on the Skill. No `login_site` tool. No Zhihu x-zse bypass.
- Do not commit unless the user explicitly asks. Do not commit `data/downloads/`.
- Do not put item arrays or answer bodies on `CollectDatasetOutput`.
- Replace prompt rule 10 (model paginates in chat) — it contradicts this Skill.

## File map

- Create: `backend/skills/collect.py` — aliases, pagination, Zhihu rewrite, write `dataset.json`
- Create: `tests/test_collect.py`
- Modify: `backend/skills/models.py` — `CollectDatasetInput` / `CollectDatasetOutput`
- Modify: `backend/skills/registry.py` — register after `scrape_page`
- Modify: `backend/agent/prompt.py` — collect routing; truncation warning
- Modify: `backend/agent/engine.py` — preview for `path` + `count`
- Modify: `tests/test_registry.py` — `collect_dataset` in tools/prompt/infos
- Modify: `tests/test_engine_limits.py` — preview does not include item bodies
- Modify: `frontend/src/components/Message.tsx` — tool card labels
- Modify: `README.md` — one short paragraph

---

### Task 1: Models, field aliases, max_items clamp

**Files:**
- Modify: `backend/skills/models.py`
- Create: `backend/skills/collect.py` (helpers only in this task)
- Test: `tests/test_collect.py`

- [ ] **Step 1: Write failing tests**

```python
from backend.skills.collect import clamp_max_items, normalize_fields
from backend.skills.models import CollectDatasetInput


def test_collect_input_schema_has_no_request_id() -> None:
    props = CollectDatasetInput.model_json_schema()["properties"]
    assert "url" in props
    assert "fields" in props
    assert "request_id" not in props
    assert "cookie" not in props and "cookies" not in props


def test_normalize_fields_maps_chinese_aliases() -> None:
    assert normalize_fields(["正文", "作者"]) == ["content", "author"]
    assert normalize_fields(["回答", "答主"]) == ["content", "author"]


def test_clamp_max_items() -> None:
    assert clamp_max_items(0) == 1
    assert clamp_max_items(46) == 46
    assert clamp_max_items(999) == 200
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_collect.py::test_normalize_fields_maps_chinese_aliases -q` — expect import failure.

- [ ] **Step 3: Implement** in `backend/skills/models.py`:

```python
class CollectDatasetInput(BaseModel):
    url: str
    fields: list[str] = Field(min_length=1)
    max_items: int = Field(default=50, ge=1, le=200)
    format: str = "json"


class CollectDatasetOutput(BaseModel):
    url: str
    path: str = ""
    count: int = 0
    fields: list[str] = Field(default_factory=list)
    truncated: bool = False
    error: str | None = None
    hint: str | None = None
```

In `backend/skills/collect.py`:

```python
MAX_ITEMS = 200
FIELD_ALIASES = {
    "正文": "content",
    "内容": "content",
    "回答": "content",
    "作者": "author",
    "答主": "author",
    "up主": "author",
    "up 主": "author",
    "标题": "title",
    "时间": "published_at",
    "日期": "published_at",
    "点赞": "voteup_count",
    "赞同": "voteup_count",
}

def clamp_max_items(value: int) -> int:
    return max(1, min(MAX_ITEMS, int(value)))

def normalize_fields(fields: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in fields:
        key = FIELD_ALIASES.get(raw.strip().lower(), raw.strip().lower().replace(" ", "_"))
        # also map exact Chinese without lowercasing CJK:
        key = FIELD_ALIASES.get(raw.strip(), key)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out
```

Fix alias lookup: try original strip first (`正文`), then lowercased for English. `UP 主` should hit `up 主` after casefold of latin only — keep a loop: `FIELD_ALIASES.get(raw.strip()) or FIELD_ALIASES.get(raw.strip().lower()) or slug`.

- [ ] **Step 4: Re-run tests — pass**

---

### Task 2: JSON pagination + projection (injectable fetcher)

**Files:**
- Modify: `backend/skills/collect.py`
- Test: `tests/test_collect.py`

- [ ] **Step 1: Failing tests** with a fake async `fetch(url) -> tuple[int, str, str]` returning `(status, content_type, body)`.

Two pages: first JSON `{"data": [20 objects], "paging": {"is_end": false, "next": "https://example.com/api/page2"}}`, second 26 objects `is_end: true`. Each object: `{"author": {"name": "A"}, "content": "正文…", "url": "https://example.com/a/N"}`.

```python
@pytest.mark.asyncio
async def test_collect_two_json_pages_writes_46_items(tmp_path: Path) -> None:
    ...
    result = await collect_dataset(
        "https://example.com/api/list",
        fields=["作者", "正文"],
        max_items=50,
        dest_dir=tmp_path,
        fetch=fake_fetch,
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.error is None
    assert result.count == 46
    assert result.truncated is False
    assert result.path.endswith("dataset.json")
    dumped = result.model_dump()
    assert "正文" not in str(dumped) or True  # stronger: no item bodies
    assert "第一条" not in json.dumps(dumped, ensure_ascii=False)
    rows = json.loads(Path(result.path).read_text(encoding="utf-8"))
    assert len(rows) == 46
    assert rows[0]["author"]
    assert rows[0]["content"]
    assert "url" in rows[0]
```

```python
@pytest.mark.asyncio
async def test_collect_respects_max_items_truncated(tmp_path: Path) -> None:
    # same fake, max_items=10
    assert result.count == 10
    assert result.truncated is True
    assert len(json.loads(Path(result.path).read_text())) == 10
```

- [ ] **Step 2: Run tests — fail** (missing `collect_dataset`).

- [ ] **Step 3: Implement**

`collect_dataset(url, *, fields, max_items=50, format="json", dest_dir=None, fetch=None, resolver=None, cancel_event=None, cookie_jar=None) -> CollectDatasetOutput`

- `validate_fetch_url` first; SafetyError → `error`, no file.
- `format != "json"` → `error` 含不支持, no file.
- Loop: fetch current URL; if status >= 400 return HTTP error (no file); parse JSON if possible.
- `extract_json_page(payload) -> tuple[list[dict], str | None]` next URL from `paging.next` if not `paging.is_end`.
- `project_item(raw, fields) -> dict` using author.name / content|excerpt / url.
- Stop on max_items, no next, empty page.
- Write `dest_dir / "dataset.json"` (mkdir). If `dest_dir` is None, caller in Skill uses `sandbox_download_dir`.
- Return path/count/fields/truncated. Never attach `items`.

- [ ] **Step 4: Tests pass**

---

### Task 3: Failures — SSRF, format, login wall, no list

**Files:**
- Modify: `backend/skills/collect.py`
- Test: `tests/test_collect.py`

- [ ] **Step 1: Tests**

```python
@pytest.mark.asyncio
async def test_collect_rejects_loopback() -> None:
    result = await collect_dataset("http://127.0.0.1/api", fields=["content"])
    assert result.error
    assert result.path == ""

@pytest.mark.asyncio
async def test_collect_rejects_csv_format(tmp_path: Path) -> None:
    result = await collect_dataset(
        "https://example.com/api",
        fields=["content"],
        format="csv",
        dest_dir=tmp_path,
        fetch=lambda *_: (_ for _ in ()).throw(AssertionError("must not fetch")),
        resolver=lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert result.error
    assert not (tmp_path / "dataset.json").exists()

@pytest.mark.asyncio
async def test_collect_login_wall_does_not_write(tmp_path: Path) -> None:
    async def fetch(url: str):
        return 200, "text/html", "<html><head><title>请登录</title></head><body>请先登录后查看完整内容</body></html>"
    result = await collect_dataset(..., dest_dir=tmp_path, fetch=fetch, resolver=...)
    assert "登录" in (result.error or "")
    assert not (tmp_path / "dataset.json").exists()

@pytest.mark.asyncio
async def test_collect_unparseable_html_does_not_dump_body(tmp_path: Path) -> None:
    async def fetch(url: str):
        return 200, "text/html", "<html><body><p>hello unique-secret-body</p></body></html>"
    result = await collect_dataset(..., dest_dir=tmp_path, fetch=fetch, resolver=...)
    assert "无法抽取列表" in (result.error or "")
    assert "unique-secret-body" not in json.dumps(result.model_dump(), ensure_ascii=False)
```

- [ ] **Step 2–4: Implement login-wall via `detect_login_wall` after HTML decode; HTTP errors; HTML fallback may return [] → 无法抽取列表. Pass.**

---

### Task 4: Zhihu question URL → answers API

**Files:**
- Modify: `backend/skills/collect.py`
- Test: `tests/test_collect.py`

- [ ] **Step 1: Test** `rewrite_list_url("https://www.zhihu.com/question/2083005795185312347")` equals  
  `https://www.zhihu.com/api/v3/question/2083005795185312347/answers?limit=20&offset=0&order_by=default`

Fake fetch on the API URL returns one Zhihu-shaped item (`author.name`, `excerpt`, `url`). `collect_dataset` on the **question page URL** must call the API URL and write `author`/`content`.

- [ ] **Step 2–4: Implement `rewrite_list_url`.** If already `/api/`, leave as-is. Pass.

---

### Task 5: Live httpx fetch + Cookie header + Skill wrapper

**Files:**
- Modify: `backend/skills/collect.py`
- Test: `tests/test_collect.py`

- [ ] **Step 1: Test** MockTransport: Cookie `z_c0` from CookieJar is sent; JSON list of 2 items written.

Mirror `tests/test_scraper.py::test_scrape_page_sends_jar_cookies` (resolver + jar + mock).

Default `_httpx_fetch` copies scrape_page patterns: Cookie header, `/api/` → `Accept: application/json`, no follow_redirects loop needed if Mock returns 200 (still handle 3 redirects like scraper). Reuse `validate_fetch_url` / `pinned_getaddrinfo` when owning the client.

`CollectSkill`:

```python
class CollectSkill:
    name = "collect_dataset"
    extras = None
    available = True
    input_model = CollectDatasetInput
    description = (
        "Collect a list/API into a local JSON file (dataset.json). "
        "Use when the user wants many items saved (fields like author/content). "
        "Do not return item bodies; return path and count. Cookies attach automatically."
    )
    routing = (
        "用户要保存/导出/全部 N 条结构化数据时用 collect_dataset，"
        "禁止用 scrape_page 把列表全文贴进聊天。"
        "成功后用返回的 path 告诉用户文件在哪。"
    )
    async def run(...):
        dest = sandbox_download_dir(context.request_id)
        return await collect_dataset(..., dest_dir=dest, cancel_event=context.cancel_event)
```

- [ ] **Step 2–4: Implement. Tests pass.**

---

### Task 6: Registry, prompt, engine preview

**Files:**
- Modify: `backend/skills/registry.py` — `from backend.skills.collect import CollectSkill` and insert after `ScrapePageSkill()`
- Modify: `backend/agent/prompt.py` — replace rule 10; add collect rules
- Modify: `backend/agent/engine.py` — `_preview_from_output`
- Modify: `tests/test_registry.py`
- Modify: `tests/test_engine_limits.py` (or `tests/test_collect.py` for preview)

Prompt changes:

- Rule 9: 登录后列表保存用 `collect_dataset`，不要把知乎 `/api/v3` JSON 当聊天全文。
- Rule 10: 条数多或 scrape_page.truncated 时，必须说明聊天会截断、继续展示等于任务失败；请用户选 `collect_dataset`（保存 JSON）或只摘要前 N 条。禁止把截断正文当成完整结果。禁止让用户自己 curl。用户已说保存/导出/json 时直接 `collect_dataset`。

Engine:

```python
    path = data.get("path")
    count = data.get("count")
    if isinstance(path, str) and path and isinstance(count, int):
        preview = f"已保存 {count} 条 · json\n{path}"
        return preview[:PREVIEW_LIMIT], None
```

Place this **before** the generic `json.dumps(data)` fallback, after `files` handling.

Tests:

- `collect_dataset` in `openai_tools()` and `skill_infos` names (after `scrape_page`).
- Prompt contains `collect_dataset` and `截断`.
- `_preview_from_output(CollectDatasetOutput(..., path="/tmp/dataset.json", count=46))` contains `46` and path, not a fake `content` even if someone stuffed extra fields — output model has no content field.

- [ ] **Step 2–4: Implement. `.venv/bin/python -m pytest tests/test_registry.py tests/test_collect.py tests/test_engine_limits.py -q` pass.**

---

### Task 7: Frontend + README

**Files:**
- Modify: `frontend/src/components/Message.tsx` — import `Save` or `FileJson` from lucide-react:

```ts
  collect_dataset: { icon: FileJson, running: "正在保存数据集", done: "已保存数据集" },
```

- Modify: `README.md` — short note: 批量列表用对话确认字段后调用 `collect_dataset`，文件在 `data/downloads/<request_id>/dataset.json`。

No new format picker.

- [ ] **Step 1: Manual** — reload Web, empty state still shows login hint; tool card exists when skill runs (covered by unit tests for registry).

---

### Task 8: Full suite

- [ ] **Step 1: Run** `.venv/bin/python -m pytest -q`  
  Expected: all previous tests plus new ones green. Update `test_skill_infos` exact name list to include `collect_dataset` immediately after `scrape_page`.

---

## Spec coverage

| Spec | Task |
| --- | --- |
| One `dataset.json` array | 2 |
| 46-item two-page JSON | 2 |
| max_items truncated | 2 |
| Aliases 正文→content | 1 |
| No item bodies in output/preview | 2, 6 |
| SSRF | 3 |
| format=csv no file | 3 |
| Login wall no file | 3 |
| 无法抽取列表, no dump | 3 |
| Zhihu question → API | 4 |
| Cookie header | 5 |
| sandbox dir via Skill | 5 |
| Prompt reminder / collect routing | 6 |
| Engine preview path+count | 6 |
| Frontend card | 7 |
| No extras dependency | 5 (`available` True) |
| No Cookie param | 1 |
| No x-zse | (omitted) |
