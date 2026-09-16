# Collect Dataset Skill 设计

日期：2026-09-16  
状态：规格已通过；实现计划见 `docs/superpowers/plans/2026-09-16-collect-dataset.md`

## 1. 问题

聊天无法承载「46 条知乎回答」这类结构化抓取：`scrape_page` 会把正文塞进模型上下文，约 9–12k 字符截断，一轮最多 6 次工具。结果是任务失败，模型还容易把截断内容当成全文，或把 curl / 贴 Cookie 甩给用户。

视频下载已经解决同类问题：文件进 `data/downloads/{request_id}/`，聊天只回路径。网页批量抓取应对齐这一形态。

## 2. 目标

用户在聊天里只确认：**抓哪些内容、要哪些字段、保存为什么格式**。确认后由新 Skill 在内部翻页、投影字段、写成一份 JSON。对话里只出现条数、本地路径、是否截断。

成功标准（第一版验收）：

- 知乎问题页（或对应 `/api/v3/question/{id}/answers` 分页）能收集到最多 46 条量级的回答数组。
- 磁盘上只有一份 `dataset.json`（JSON 数组），不是 46 个小文件，也不是 jsonl。
- 工具返回与聊天预览都不含条目正文，也不含 Cookie 值。
- 用户未点名保存时，不建任务目录；但内容会撑爆聊天时必须主动提醒并给出选择。

## 3. 非目标（第一版）

- Excel / PDF / CSV 导出
- 前端选择保存目录、打开 Finder、下载按钮（路径用文本展示即可）
- 断点续传（每次任务一份新 `dataset.json`）
- 每页再调模型做抽取
- 绕过知乎 403/462 等签名风控
- 工具参数增加 Cookie 字段；用户把 Cookie 贴进对话
- 把完整 46 条贴进聊天或 SSE preview
- 多用户、云端同步文件

## 4. 已锁定决策

| 项 | 选择 |
| --- | --- |
| 何时落盘 | 用户明确要保存（json / 导出 / 抓全部并落盘）。**例外：** 内容太多时必须先提醒，不能干等用户想起口令 |
| 文件形态 | 任务目录一份数组 JSON |
| 谁翻页 | 新 Skill `collect_dataset` 内部完成，不让模型循环 `scrape_page` |
| 覆盖范围 | 通用入口（URL + 字段）；JSON API 优先，HTML 列表尽力；知乎问答作验收 |
| 目录 | 与视频相同：`data/downloads/{request_id}/`（`sandbox_download_dir`） |
| 文件名 | `dataset.json` |

## 5. 用户流程

1. 用户给出 URL，并说要「全部回答 / 作者和正文 / 保存为 json」等。
2. 若意图已是落盘：直接 `collect_dataset`。
3. 若意图仍是聊天展示，但 `scrape_page` 返回 `truncated`，或用户要的条数明显装不进对话：
   - 禁止把截断正文当完整结果。
   - 明确告知：聊天展示不全会被截断，继续写等于任务失败。
   - 给出选择：调用 `collect_dataset` 保存 JSON，或只摘要前 N 条。
4. 用户选定字段与格式后，Skill 执行，聊天汇报路径与 `count`。

## 6. 架构

模型仍然只选 Skill，不选分页实现、不选登录方案。

```
用户消息（URL + 字段 + 要保存）
        │
        ▼
   collect_dataset
        │
        ├─ SSRF / CookieJar（与 scrape_page 相同）
        ├─ 识别列表：JSON API 分页优先 → 否则 HTML 列表
        ├─ 按 fields 投影（缺字段为 null，不编造）
        └─ 写入 sandbox_download_dir(request_id)/dataset.json
        │
        ▼
   返回 { path, count, fields, truncated, error }
   preview 仅「已保存 N 条 · json」+ path
```

`scrape_page` 继续负责单页阅读。列表过大时 `hint=collect_dataset`（hint 必须是已启用 Skill 名）。

登录态：CookieJar 自动附加。无哨兵或登录墙 → `需要登录` + `tools.login`，**不写文件**。不做 WAF/签名绕过。

## 7. Skill 契约

**名称：** `collect_dataset`  
**默认可用**（不依赖 extras）。内部复用 httpx + CookieJar，与 `scrape_page` 同级。

### 输入

| 字段 | 规则 |
| --- | --- |
| `url` | 必填。http(s) 列表页、问题页或 `/api/` JSON。 |
| `fields` | 字符串数组，至少 1 个。用户点名的逻辑字段。 |
| `max_items` | 默认 50，范围 1–200（需覆盖 46 条验收）。 |
| `format` | 第一版只接受 `json`；其他值返回错误，不写文件。 |

不要 `request_id`（与现有 Skill 一样由 `SkillContext` 提供）。不要 Cookie 参数。

### 输出

| 字段 | 含义 |
| --- | --- |
| `url` | 请求 URL |
| `path` | 成功时 `dataset.json` 的绝对或沙箱内路径 |
| `count` | 实际写入条数 |
| `fields` | 规范化后的字段名列表 |
| `truncated` | 因 max_items / 超时 / 分页未结束而提前停 |
| `error` | 失败原因；成功为 null |
| `hint` | 仅在「应改用其他 Skill」时使用；本 Skill 成功时为 null |

**禁止**在输出中包含条目数组或正文。引擎 `_content_for_llm` / `_preview_from_output` 必须按 `path`+`count` 生成预览，不能把文件内容读进模型。

### 字段投影

用户中文别名映射到稳定键，未知名称保持原样（小写、去空白）：

| 用户说法 | 键 |
| --- | --- |
| 正文、内容、回答 | `content` |
| 作者、答主、UP 主 | `author` |
| 标题 | `title` |
| 时间、日期 | `published_at` |
| 点赞、赞同 | `voteup_count` |

每条对象：点名的键 + 自动 `url`（源里有则填，没有为 `null`）。源没有的点名键为 `null`，不编造。

### 分页停止（先到先停）

1. `count >= max_items`
2. API 结束标记（如知乎 `paging.is_end`）
3. 连续一页 0 条
4. 总超时 120 秒
5. 登录墙

中途停止：把已有条目写入 `dataset.json`，`truncated=true`，`count` 为实际条数。聊天说明「已保存 N 条，未抓完」，不贴半截正文。

超时与 `max_items` 截断仍算**工具成功**（有文件）；登录墙、风控、无法抽取、写盘失败算**工具失败**（无文件，或写盘失败时不假装成功）。

### 失败

| 情况 | 行为 |
| --- | --- |
| 未登录 / 登录墙 | `error` 含「需要登录」和 `tools.login`；不写文件 |
| HTTP ≥400（含 403/462） | 报告状态码；说明不是缺 Cookie；不绕过；不写文件 |
| 非 JSON 列表且 HTML 抽不出列表 | `无法抽取列表`；不把整页 Markdown 塞进聊天或输出 |
| `format` 非 json | 错误；不写文件 |
| 写盘失败 | `error`；不声称已保存 |

## 8. 列表识别（第一版）

**优先 JSON：**

- URL 路径含 `/api/`，或响应 `Content-Type` / 正文为 JSON。
- 若根对象有 `data` 且为对象数组，则视为列表页；分页跟随 `paging.next` 或 `paging.is_end` + `offset`/`limit`（知乎验收用这个）。
- 若根是数组，则整段即本页条目，无下一页。

**否则 HTML：** 尽力抽取链接列表或重复卡片；抽不出则失败。第一版不要求任意站点都成功。

**知乎验收约定：**

- 输入可以是 `https://www.zhihu.com/question/{id}`，Skill 内部转到 answers API 分页（`limit` 与 `offset`）。
- 条目映射：作者名 → `author`，回答正文（纯文本或已有 excerpt/content）→ `content`，回答 URL → `url`。
- 带 CookieJar 的 `z_c0` 等；仍 403/462 则按风控失败，不实现 x-zse。

内部请求复用 `scrape_page` 的 Cookie 头、SSRF、host 间隔；JSON 正文走已有 `json_body_to_markdown` 的解析路径或等价 `json.loads`，**不要**把每页 JSON 再截断进模型。本 Skill 的页内限制是 `max_items` 和 120s，不是 12k 字符。

## 9. 提示词与路由

系统提示增加：

- 用户要保存/导出/全部 N 条结构化数据 → `collect_dataset`，不要用 `scrape_page` 把全文贴进聊天。
- `scrape_page` 报 truncated 或 empty 且意图是列表 → 说明截断会导致任务失败，`hint`/`collect_dataset`，等待用户选「保存 JSON」或「只摘要前 N」。
- 禁止声称没有工具能保存文件；禁止让用户 curl / 贴 Cookie。
- 成功后用工具返回的 `path` 告诉用户文件在哪（与 `download_media` 相同）。

`collect_dataset.description` 写明：批量列表写入本地 JSON，不把条目正文返回给模型。

## 10. 前端

- 工具卡：进行中「正在保存数据集」；完成「已保存数据集」。
- 预览：`已保存 {count} 条 · json` 与 `path`。不渲染 JSON 数组。
- 不新增保存按钮或格式选择器；选择发生在对话文本里。
- 输入栏保持「不要把 Cookie 贴进对话框」。

## 11. 测试

- 假 JSON 两页（20+26）→ `dataset.json` 长度 46，含 `content`/`author`，工具输出不含条目正文。
- `max_items=10` → `count=10`、`truncated=true`、文件 10 条。
- 登录墙 / 无 Cookie → 不写文件。
- 别名：`正文` → `content`。
- 系统提示含 `collect_dataset` 与截断提醒。
- Cookie 值不出现在 preview / 工具 JSON。
- SSRF：loopback URL 被拒。
- `format=csv` → error，不写文件。

## 12. 文件改动（实现时）

- 新增：`backend/skills/collect.py`、`tests/test_collect.py`
- 修改：`backend/skills/models.py`、`registry.py`、`prompt.py`、`engine.py`（preview 规则）、`frontend/src/components/Message.tsx`、`README.md`（可选短节）

不把 `data/downloads/` 纳入 git（已在 `data/` ignore）。
