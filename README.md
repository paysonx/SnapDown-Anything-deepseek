# SnapDown-Anything · 万能视频下载器

单页网站 + 服务端下载：粘贴链接 → 解析 → 选清晰度 → 排队下载 → 真实进度 → 保存到设备。
首版支持 **B站、抖音、YouTube** 的单个点播视频（含 `b23.tv`、`v.douyin.com`、`youtu.be` 短链与抖音分享文案）。

- B站 / 抖音**强制直连**；YouTube**只走代理**（本机客户端代理优先，服务器端代理兜底），不可用即停止，不回退直连。
- 下载在服务端运行：关页不中断；服务重启后标记「已中断」，重试复用 `.part` 分片续传。
- 保留源画质，FFmpeg 无损合并，不重新编码。

> 仅处理公开且你有权保存的内容；不绕过 DRM、会员权限与付费限制。

## 1. 环境

- Windows 11（实测）/ macOS / Linux
- Python 3.11+（实测 3.13.17）
- FFmpeg + FFprobe 在 PATH（实测 9.0.2）
- Node.js 20+ 与 pnpm（仅构建前端）；`web/dist` 不入库，首次必须执行第 2 节的构建

## 2. 首次安装

一键（建 venv → 装依赖 → 构建前端 → 启动）：

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

手动等价步骤：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd web; pnpm install; pnpm build; cd ..
```

- 版本锁定见 `requirements.txt`（`fastapi 0.162.0` / `uvicorn 0.54.0` / `yt-dlp 2026.10.21`）。
- 解析失败先升级 yt-dlp：`.\.venv\Scripts\python.exe -m pip install -U yt-dlp`
- 直接运行报「未对文件进行数字签名」时，用上面的 `-ExecutionPolicy Bypass` 写法。
- 装完自检：

```powershell
.\.venv\Scripts\python.exe -V
Test-Path web\dist\index.html
.\.venv\Scripts\python.exe -m pytest -q    # 需先装 requirements-dev.txt，预期 43 passed
```

## 3. 运行

```powershell
.\run.ps1
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

`-Port 9000` 换端口、`-Rebuild` 重建前端、`-SkipInstall` 跳过依赖安装。打开 <http://127.0.0.1:8787>。

停止：`Get-NetTCPConnection -LocalPort 8787 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }`

前端开发态：`cd web; pnpm dev`（5173，`/api` 代理到 8787）

## 4. 配置（环境变量或项目根 `.env`）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8787` | 服务监听地址 |
| `DATA_DIR` | `.data` | 数据库、分片与成品目录 |
| `WEB_DIST` | `web/dist` | 前端产物目录 |
| `PROXY_MODE` | `auto` | `auto` 本机优先/服务器兜底；`local`、`server` 锁定单一路径；`off` 关闭 |
| `PROXY_LOCAL` | 空 = 自动探测系统代理 | 本机客户端代理，如 `http://127.0.0.1:10808` |
| `PROXY_SERVER` | 空 | 服务器端代理兜底 |
| `PROXY_PROBE_URL` | `https://www.youtube.com/generate_204` | 代理健康检查地址 |
| `PROXY_PROBE_TIMEOUT` | `6` | 健康检查超时（秒） |
| `COOLDOWN_SECONDS` | `bilibili:3,douyin:5,youtube:3` | 平台冷却秒数，格式 `平台:秒`，逗号分隔 |
| `MAX_ACTIVE_TASKS` | `3` | 并发任务上限 |
| `MAX_INPUT_CHARS` | `2000` | 单次输入字符上限 |
| `FILE_TTL_HOURS` | `24` | 成品文件保留时长 |
| `WORK_TTL_DAYS` | `7` | 中断/失败任务的工作目录保留天数 |
| `LOG_LEVEL` | `INFO` | 后端日志级别 |
| `USER_AGENT` | Chrome UA | 传给 yt-dlp 的 UA |
| `FFMPEG_PATH` / `FFPROBE_PATH` | 空 = 走 `PATH` | 显式指定二进制路径 |
| `DEV_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 开发态跨域来源 |

`.env` 仅在启动时读取一次，改动需重启。代理凭据只从环境变量读取。

## 5. 目录

```
run.ps1              一键启动
requirements.txt     运行依赖（版本锁定）
requirements-dev.txt 测试依赖
.env.example         全部可配置项模板
LICENSE              MIT
app/                 后端
  config.py          环境配置、路径、冷却
  platforms.py       链接/分享文案提取、平台识别
  security.py        输入校验与 SSRF 白名单
  store.py           SQLite 持久化
  limiter.py         按平台队列与冷却
  proxy.py           代理候选、健康检查、路由选择
  ytdlp_runner.py    yt-dlp 解析/下载/进度/合并/校验
  jobs.py            任务状态机、队列、清理、重启恢复
  events.py          SSE 订阅与快照
  api.py             REST + SSE + 文件下载
web/                 React 19 + Vite 前端
tests/               pytest（43 个用例，全部离线）
scripts/             screenshot.mjs：验收截图（Chrome DevTools Protocol）
docs/                需求与架构文档（截图与 logo 源图仅本地保留，不入库）
```

## 6. API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | yt-dlp / ffmpeg / 代理状态 |
| `GET` | `/api/tasks` | 任务列表 + 平台队列快照 |
| `POST` | `/api/tasks` | `{ "text": "链接或抖音分享文案" }` 创建并解析 |
| `GET` | `/api/tasks/{id}` | 单任务 |
| `POST` | `/api/tasks/{id}/download` | `{ "option_id": "fmt-30080" }` 入队下载 |
| `POST` | `/api/tasks/{id}/retry` | 重试（复用分片） |
| `POST` | `/api/tasks/{id}/cancel` | 取消并清理临时文件 |
| `GET` | `/api/events` | SSE 快照流（整页一条连接，约每秒一帧） |
| `GET` | `/api/tasks/{id}/file` | 下载成品，支持 `Range` |

## 7. 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

43 个离线用例（注入 FakeDownloader，不触网）：链接提取、SSRF 白名单、状态迁移、平台冷却与排队、SSE 帧、重启恢复、清理、代理选择。

## 8. 已知限制

- 抖音真实下载未端到端验证（缺有效分享短链样本），平台风控可能导致失败，失败原因如实展示。
- 未配置 Deno 时部分 YouTube 格式可能缺失。
- 不含账号、Cookie 上传、播放列表/批量、直播、会员与 DRM 内容。
- 单用户本机使用；多人共享需自行加鉴权与资源隔离。

## 9. 许可

[MIT](LICENSE)
