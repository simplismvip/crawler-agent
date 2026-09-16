# Crawler Agent

本机网页检索助手：把链接丢进对话，它去搜、读页面、需要时下载。Web 和命令行共用同一套后端。

需要 Python 3.12，虚拟环境用 uv 建在 `.venv`。

## 先跑起来

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -r backend/requirements.txt
cp .env.example .env          # 填 MiniMax Key；搜索地址按你的 SearXNG 改
cd frontend && npm install
```

两个终端：

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev    # http://localhost:3000 ，/api 会转到后端
```

或直接命令行：

```bash
.venv/bin/python -m cli "抓取 https://news.ycombinator.com 首页前 5 条，用表格列出标题和链接。"
```

对话存在本机 `data/crawler-agent.db`。顶栏可切换 MiniMax 模型。

渲染页、下视频、下图集是可选能力，未装时对话里看不到对应工具：

```bash
uv pip install --python .venv/bin/python -r backend/requirements-extras.txt
# 渲染还要按 crawl4ai 文档装浏览器
```

## 登录后再抓

不要给日常 Chrome 开远程调试。扫码用专用窗口：

```bash
.venv/bin/python -m tools.login --platform xhs    # 或 bili / zhihu / dy / wb
```

登录成功才写入 `data/cookies/`。小红书必须出现真正的 `web_session`（只有设备指纹 `a1` 不算登录）。Cookie 不会进对话。

## 小红书 / 知乎问答等

国内社交不要靠普通网页抓取。另外克隆 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)，在 `.env` 写上：

```bash
MEDIACRAWLER_HOME=/absolute/path/to/MediaCrawler
```

```bash
git clone https://github.com/NanmiCoder/MediaCrawler.git ../MediaCrawler
cd ../MediaCrawler && uv sync
.venv/bin/playwright install chromium-headless-shell
```

然后把**完整链接**发给助手。小红书请用：

- 笔记：`/explore/{id}?xsec_token=...` 或带 token 的 `/discovery/item/...`
- 作者主页：`/user/profile/{id}?xsec_token=...`（创作者接口有时比单条笔记更容易被拦）

`/explore` 首页不够。不会接管你的日常 Chrome。

## 列表太长

要保存「正文 + 作者」这类字段、或聊天里贴不下时，在对话里说保存为 json。文件在 `data/downloads/<request_id>/dataset.json`，聊天只回路径和条数。这是按内容体量用的，不是某个网站的专用功能。

## 测试

```bash
.venv/bin/python -m pytest
```

本项目是个人学习用的检索助手，不对抗验证码，也不做多用户。设计笔记在 `docs/`。

## 免责声明 / Disclaimer

本软件仅供个人学习、研究与合规的公开信息检索使用。

1. 使用者应严格遵守相关法律法规，尊重各目标网站的 `robots.txt` 协议及服务条款。
2. 严禁利用本工具从事任何侵犯第三方合法权益、违规批量获取非公开数据或破坏计算机信息系统的行为。
3. 作者不对因使用者不当使用本软件而造成的任何直接或间接法律责任及损失承担任何责任。

This software is intended strictly for educational, research, and compliant public information retrieval purposes.

1. Users must comply with local laws, regulations, and the respective targets' Terms of Service and `robots.txt`.
2. Any misuse of this tool for illicit purposes or unauthorized data acquisition is strictly prohibited.
3. The authors and contributors assume no liability for any damages or legal consequences arising from the use of this software.
