# Crawler Agent

公开网页检索 Agent：原生 OpenAI function calling。默认两个工具（`search_web` / `scrape_page`），V1.2 起可按 extras 启用渲染、媒体、图集、社交 Skill。CLI 与 Web 共用事件流。

Python 3.12，环境在 `.venv`（由 uv 创建）。

## 当前默认

| 项   | 当前                                                                                             | 后期                                  |
| --- | ---------------------------------------------------------------------------------------------- | ----------------------------------- |
| 搜索  | 树莓派 SearXNG：`SEARXNG_BASE_URL=http://100.120.153.107:8888`（Tailscale）。未配时才 Tavily / DuckDuckGo | 可切换 SearXNG / Tavily / DuckDuckGo 等 |
| 模型  | 默认 MiniMax-M3；Web 顶栏可切换 MiniMax M 系列（同一兼容网关）                                                   | 其他厂商网关                              |
| Web | Gemini 浅色对话壳：侧边栏历史、胶囊输入、SQLite 落库                                                              | 多用户 / 登录                            |
| 抓取  | 默认 `httpx + trafilatura`，列表页 `markdownify`。可选 extras：Crawl4AI / yt-dlp / gallery-dl            | 反爬套件                                |

会话存在本机 `data/crawler-agent.db`（可用 `SQLITE_PATH` 覆盖）。

## 登录态（V1.3）

不要给日常 Chrome 开 `--remote-debugging-port`。在专用窗口扫码，脚本轮询关键 Cookie 后再导出：

```bash
.venv/bin/python -m tools.login --platform xhs    # 或 bili / zhihu / dy / wb
```

成功后写入 `data/cookies/{platform}.json`（Playwright `storage_state`，含 localStorage）和 `{platform}.netscape.txt`（给 yt-dlp）。没有哨兵 Cookie（例如小红书 `web_session`/`a1`）不会写出游客态。

`GET /api/cookies` 只返回各平台是否已配置（布尔），不含 Cookie 值。

可选：`COOKIES_FROM_BROWSER=chrome` 让 yt-dlp 直接读本机浏览器 Cookie 库。**默认不要开。** macOS 会弹出钥匙串；日常 Chrome 开着时常见 `Database is locked`。出问题请改用上面的 Netscape 文件。

## 批量保存（collect_dataset）

列表很长、要正文+作者等字段、或任意抓取结果会被聊天截断时，在对话里说明字段和「保存为 json」。**按任务体量触发，不限网站**（知乎问答页只是把 HTML 改写成 answers API 的适配样例）。工具会写入 `data/downloads/<request_id>/dataset.json`，聊天只显示路径和条数，不会把全文贴进对话。内容太多会被截断时，助手应提醒改走保存，而不是继续往聊天里倒。

## 安装

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -r backend/requirements.txt
cp .env.example .env
```

可选能力（未装则模型看不到对应工具，`GET /api/skills` 会给出安装命令）：

```bash
uv pip install --python .venv/bin/python -r backend/requirements-extras.txt
# 渲染页还需要按 crawl4ai 文档安装浏览器
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

不做并行工具执行、Cloudflare 对抗、多用户。登录态用你自己的会话（`tools.login` 或 Cookie 文件），不是绕过验证码。详见 `docs/V1.3.md`。



## 免责声明 / Disclaimer

本软件仅供个人学习、研究与合规的公开信息检索使用。

1. 使用者应严格遵守相关法律法规，尊重各目标网站的 `robots.txt` 协议及服务条款。
2. 严禁利用本工具从事任何侵犯第三方合法权益、违规批量获取非公开数据或破坏计算机信息系统的行为。
3. 作者不对因使用者不当使用本软件而造成的任何直接或间接法律责任及损失承担任何责任。

This software is intended strictly for educational, research, and compliant public information retrieval purposes.

1. Users must comply with local laws, regulations, and the respective targets' Terms of Service and `robots.txt`.
2. Any misuse of this tool for illicit purposes or unauthorized data acquisition is strictly prohibited.
3. The authors and contributors assume no liability for any damages or legal consequences arising from the use of this software.
