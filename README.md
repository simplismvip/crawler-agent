# Crawler Agent

公开网页检索 Agent：原生 OpenAI function calling、两个工具（`search_web` / `scrape_page`）、CLI 与 Web 共用事件流。

Python 3.12，环境在 `.venv`（由 uv 创建）。

## 当前默认

| 项 | 当前 | 后期 |
| --- | --- | --- |
| 搜索 | 树莓派 SearXNG：`SEARXNG_BASE_URL=http://100.120.153.107:8888`（Tailscale）。未配时才 Tavily / DuckDuckGo | 可切换 SearXNG / Tavily / DuckDuckGo 等 |
| 模型 | 默认 MiniMax-M3；Web 顶栏可切换 MiniMax M 系列（同一兼容网关） | 其他厂商网关 |
| Web | Gemini 浅色对话壳：侧边栏历史、胶囊输入、SQLite 落库 | 多用户 / 登录 |

会话存在本机 `data/crawler-agent.db`（可用 `SQLITE_PATH` 覆盖）。

## 安装

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -r backend/requirements.txt
cp .env.example .env
```

本机 Docker 起 SearXNG 可选，不是当前默认：

```bash
docker compose up -d   # 仅当不用树莓派实例时
```

前端：

```bash
cd frontend && npm install
```

## 运行

后端（只绑本机）：

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

CLI：

```bash
.venv/bin/python -m cli "抓取 https://news.ycombinator.com 首页的前 5 条新闻标题与讨论链接，以 Markdown 表格输出。"
```

Web：另开终端 `cd frontend && npm run dev`，打开 http://localhost:3000 。Next 会把 `/api/*` 代理到后端。

## 测试

```bash
.venv/bin/python -m pytest
```

## 范围

不做并行工具执行、Crawl4AI、登录墙、多用户。抓页默认 `httpx + trafilatura`，列表页回退 `markdownify`，Playwright 仅作末档且默认不安装。
