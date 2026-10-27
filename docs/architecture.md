# SnapDown-Anything

> 状态：**v1.0 · 已确认并实现**（2026-10-27 验收；后续变更需人工确认）
> 依据：`docs/requirements.md`、`AGENTS.md`
> 目标：本机跑通「粘贴链接 → 解析 → 选清晰度 → 排队下载 → 真实进度 → 保存到设备」单条完整链路。

---

## 1. 技术栈（已确认并实现）

| 层 | 选型 | 理由 |
|---|---|---|
| 运行时 | Python 3.13（已装） | yt-dlp 原生语言，无语言桥接 |
| Web 框架 | FastAPI + uvicorn | 自带 ASGI/异步/SSE，依赖少 |
| 下载引擎 | yt-dlp（Python 库调用） | 直接拿到 `progress_hooks` / `postprocessor_hooks` 真实事件，免解析 CLI 文本 |
| 合并 | FFmpeg / ffprobe（已装 9.0.2） | `-c copy` 无损封装，不转码 |
| 存储 | SQLite（标准库 sqlite3，WAL） | 单文件、零额外服务、足够支撑持久化与重启恢复 |
| 前端 | React 19 + TypeScript + Vite（**已确认**），手写 CSS 变量体系 | 组件化维护任务卡/清晰度列表；样式与设计稿 1:1，不引入 Tailwind 等额外依赖 |
| 构建 | pnpm 12 + Vite，产物 `web/dist` 由 FastAPI 托管 | 生产单端口 8787；开发态 Vite 5173 反代 `/api` |
| 测试 | pytest + httpx TestClient | 单测 + 假下载器集成测试 |

**不采用**：Node/Express（yt-dlp 需子进程 + 文本解析进度，边界更多）、Redis/Celery（单机单进程，asyncio 队列足够）、Tailwind（本项目视觉为定制纸感样式，手写 CSS 变量更直接，且少一层依赖）。

**前端构建与运行**：
- 开发：`pnpm dev`（5173，`server.proxy` 把 `/api` 转到 `127.0.0.1:8787`）+ `uvicorn`（8787）。
- 交付：`pnpm build` 产出 `web/dist`，由 FastAPI 静态托管，浏览器只访问 `http://127.0.0.1:8787`。`run.ps1` 自动完成「建 venv → 装依赖 → 构建前端 → 启动」。

**后端为何用库而不是 CLI**：`progress_hooks` 直接给出 `downloaded_bytes / total_bytes / total_bytes_estimate / speed / eta / filename / info_dict`，`postprocessor_hooks` 给出 `started|processing|finished`，可准确区分「下载中」与「合并中」，并支持在 hook 中抛异常实现**即时取消**。CLI 方案只能靠 `--newline` 文本进度模板，合并阶段与取消语义都要额外绕行。

---

## 2. 架构

```
Browser (单页, EventSource)
   │  REST + SSE(1s)
   ▼
FastAPI  app/api.py
   ├─ 输入校验/平台识别/SSRF 白名单   app/platforms.py
   ├─ 任务状态机 + 编排              app/jobs.py
   │     ├─ 平台通道（并发=1 + 冷却） app/limiter.py
   │     ├─ 代理探测与选择           app/proxy.py
   │     └─ yt-dlp 封装（解析/下载） app/ytdlp_runner.py
   ├─ SSE 广播                       app/events.py
   └─ SQLite (WAL)                   app/store.py
                │
                ▼
        .data/work/<task_id>/  ← .part 分片 + 最终文件
```

进程模型：**单进程**。解析/下载在 `asyncio.to_thread` 中执行（yt-dlp 为同步阻塞库），事件循环只负责调度、SSE 与 HTTP。避免多进程导致的队列/限频状态分裂。

---

## 3. 目录结构

```
SnapDown-Anything/
├─ AGENTS.md
├─ README.md                     # 安装、配置、启动、测试
├─ requirements.txt              # 运行依赖（版本锁定）
├─ requirements-dev.txt          # pytest / httpx
├─ .env.example                  # 全部可配置项（无密钥）
├─ .gitignore                    # 分组注释：运行数据/产物/依赖/日志/本地配置
├─ .gitattributes                # 统一 LF，二进制资源不做转换
├─ LICENSE                       # MIT
├─ run.ps1                       # 一键启动（venv → 依赖 → 构建 → uvicorn）
├─ app/
│  ├─ main.py                    # 应用装配、生命周期、静态托管
│  ├─ config.py                  # 环境变量、路径、平台冷却
│  ├─ api.py                     # REST + SSE + 文件下载
│  ├─ platforms.py               # 链接/分享文案提取、平台识别
│  ├─ security.py                # 输入校验与 SSRF 白名单
│  ├─ models.py                  # 状态枚举、任务/选项/进度数据结构
│  ├─ progress.py                # 多流进度聚合（纯逻辑）
│  ├─ store.py                   # SQLite（WAL）读写
│  ├─ limiter.py                 # 按平台队列、并发、冷却
│  ├─ proxy.py                   # 代理候选、健康检查、路由选择
│  ├─ ytdlp_runner.py            # yt-dlp 解析/下载/进度映射/合并/ffprobe 校验
│  ├─ jobs.py                    # 状态机、编排、取消、重试、清理、重启恢复
│  ├─ events.py                  # SSE 订阅与 1s 快照
│  └─ errors.py                  # 错误码与用户可读文案
├─ web/
│  ├─ index.html
│  ├─ vite.config.ts             # /api 代理到 8787，build 输出 dist
│  ├─ tsconfig.json / package.json
│  ├─ public/logo.png            # 64px 图标（由本地品牌源图生成）
│  └─ src/
│     ├─ main.tsx / App.tsx
│     ├─ styles/app.css          # 设计令牌 + 组件样式
│     ├─ lib/                    # api.ts、types.ts、format.ts、useSnapshot.ts、useNow.ts
│     └─ components/             # Composer、QualityPanel、TaskProgress、TaskResult、HistoryCard、TopBar…
├─ tests/                        # 43 个离线用例（conftest 注入 FakeDownloader）
│  ├─ test_platforms.py / test_security.py
│  ├─ test_limiter.py / test_quality_options.py
│  ├─ test_proxy.py / test_restart.py
│  └─ test_api_flow.py           # 假下载器端到端
├─ scripts/
│  └─ screenshot.mjs             # 验收截图（Chrome DevTools Protocol）
├─ docs/                         # requirements.md、architecture.md（截图与 logo 源图不入库）
└─ .data/                        # 运行时（git 忽略）
   ├─ snapdown.db                # 数据库（另有 db-wal / db-shm）
   ├─ app.log
   └─ work/<task_id>/            # 分片与成品
```

---

## 4. 平台识别与输入

| 平台 | 允许 host（含子域） | 路由 | 示例 |
|---|---|---|---|
| bilibili | `bilibili.com`、`b23.tv` | 直连 | BV/av 号、`b23.tv/xxx` |
| douyin | `douyin.com`、`iesdouyin.com`、`v.douyin.com` | 直连 | `v.douyin.com/xxx`、含文案的整段分享文本 |
| youtube | `youtube.com`、`m.youtube.com`、`youtu.be` | 代理 | `watch?v=`、`youtu.be/`、`shorts/` |

输入处理流水线：

1. 若文本含 URL，用 `https?://[^\s"'<>，。！？、【】]+` 提取**第一个** URL（覆盖抖音分享文案）；否则尝试把整段文本当 URL。
2. 去掉尾部中英文标点，规范化（补协议、去 fragment、去常见跟踪参数）。
3. `urlsplit` 校验：scheme ∈ {http, https}；禁止 userinfo（`@`）；禁止 IP 字面量与私有/回环地址；端口仅允许默认端口。
4. host 与白名单做**后缀精确匹配**（`host == d or host.endswith("." + d)`），命中即确定平台；未命中 → 400「暂不支持该平台」。
5. 同 URL 若已有未结束任务，直接返回该任务（去重，防重复点击）。

> SSRF 边界：只把「白名单域名的 URL」交给 yt-dlp，从不请求用户提供的任意地址；短链跳转由 yt-dlp 在平台域内完成。不代理用户任意图片/资源。

---

## 5. 网络代理路由（后端强制，禁止回退）

```
platform.route == "direct"  → yt-dlp proxy=None（B站/抖音；失败即失败，绝不切代理）
platform.route == "proxy"   → 必须拿到可用代理，拿不到 → 任务失败
                              （YouTube；失败即失败，绝不回退直连）
```

代理候选与优先级（满足「本地客户端代理优先，服务器端兜底」）：

1. `PROXY_LOCAL`：显式配置，缺省**自动读取 Windows 系统代理**（注册表 `Internet Settings\ProxyServer`，本机实测 `127.0.0.1:10808`）。
2. `PROXY_SERVER`：服务器/远端 HTTP/SOCKS 代理。
3. 按 1→2 顺序探测，取第一个健康的；全部不可用 → `PROXY_UNAVAILABLE`，任务失败并提示「代理不可用，已停止（不会直连）」。

探测方式：TCP 连接（1.5s）+ 通过代理发 `HEAD https://www.youtube.com/generate_204`（4s）。结果缓存 60s；失败后 15s 内不重复探测，避免每个任务都等待。协议只接受 `http`、`https`、`socks5`、`socks5h`。

环境变量：

```ini
PROXY_MODE=auto            # auto | local | server | off（off=未配置代理，YouTube 直接判失败）
PROXY_LOCAL=               # 空=自动探测系统代理
PROXY_SERVER=
PROXY_PROBE_URL=https://www.youtube.com/generate_204
```
凭据只存环境变量，不写库、不进日志（日志中脱敏为 `http://***@host:port`）。

> 现状备注：本机 10808 为系统代理且可直连 YouTube；B站/抖音无需代理。三个平台的真实网络测试因此都可执行。

---

## 6. 任务状态机

| 状态 | 中文 | 说明 |
|---|---|---|
| `RESOLVE_QUEUED` | 等待解析 | 已入解析队列，展示队列位置与预计开始时间 |
| `RESOLVING` | 解析中 | 调 `extract_info(download=False)` |
| `AWAITING_SELECTION` | 待选择清晰度 | 已拿到标题/时长/清晰度，默认选「最佳可用画质」 |
| `DOWNLOAD_QUEUED` | 等待下载 | 展示队列位置与平台冷却倒计时 |
| `DOWNLOADING` | 下载中 | 真实字节/速度/ETA；分流阶段与总体进度 |
| `MERGING` | 合并中 | 音视频已下完，FFmpeg `-c copy` 封装 |
| `COMPLETED` | 已完成 | 文件存在且 ffprobe 校验通过后才进入 |
| `FAILED` | 失败 | 带错误码、可读原因、是否可重试 |
| `CANCELLED` | 已取消 | 用户取消，立即清理工作目录 |
| `INTERRUPTED` | 已中断 | 服务重启导致；保留分片，允许重试续传 |

合法迁移：

```
RESOLVE_QUEUED → RESOLVING → AWAITING_SELECTION → DOWNLOAD_QUEUED → DOWNLOADING → MERGING → COMPLETED
      │             │              │                  │               │            │
      └─────────────┴──────────────┴──────────────────┴───────────────┴────────────┴→ FAILED
                                  （任意非终态）→ CANCELLED
                                  重启时非终态 → INTERRUPTED
FAILED / CANCELLED / INTERRUPTED → 重试：有格式信息→DOWNLOAD_QUEUED；无→RESOLVE_QUEUED
```

终态：`COMPLETED / FAILED / CANCELLED / INTERRUPTED`（可重试的终态为后三者）。
所有迁移由 `jobs.transition()` 单点写入，附带 `status_reason`，并广播一次快照。

---

## 7. 队列与限频（服务端统一）

- 每个平台一个**通道**（lane）：`asyncio.Queue` + 单 worker，`concurrency = 1`，FIFO。
- 通道内两次启动之间有 `COOLDOWN_SECONDS[platform]`（默认 bilibili 3s / douyin 5s / youtube 3s），冷却期间新任务拿到 `cooldown_until` 倒计时。
- **解析、下载启动、重试**三种动作都走同一通道，因此刷新页面/重复点击无法绕过额度。
- 全局上限：`MAX_ACTIVE_TASKS=3`（非终态任务数），超出返回 429「排队任务过多，请等待当前任务结束」。
- 队列位置 = 同平台同阶段队列中的下标 + 1；预计开始时间 = 位置 × 平均任务耗时（滚动平均，样本 < 2 时返回 `null`，前端显示「估算中」）——遵守「可计算时才显示」。

---

## 8. 进度采集与 SSE

### 8.1 从 yt-dlp 映射

`progress_hooks` 每个 hook：

```python
{
  "status": "downloading" | "finished",
  "downloaded_bytes": int,
  "total_bytes": int | None,
  "total_bytes_estimate": float | None,
  "speed": float | None,
  "eta": int | None,
  "filename": str,
  "info_dict": {"format_id": ..., "vcodec": ..., "acodec": ..., ...},
}
```

任务内维护 `streams: {format_id: {kind: video|audio, downloaded, total, done}}`，hook 按 `format_id` 归并；`overall_downloaded = Σ stream.downloaded`，`overall_total = Σ stream.total` **仅在全部流已知总大小时**才给出百分比，否则 `percent = None`。

- 单流下载（B站 durl）：`phase = "single"`。
- 分流下载（YouTube）：`phase` 在 `video`/`audio` 间切换，前端显示「阶段 1/2 · 视频流」，并用聚合字节算总体进度，避免两阶段各自显示 100%。
- 合并：`postprocessor_hooks` `started` → `MERGING`（进度条转为不确定态 + 文案「音视频已下载完成，正在无损合并」）。
- 完成判定：`COMPLETED` 只在「最终文件存在 && 大小 > 0 && ffprobe 可解析 && 时长与 info 误差 < 2s」之后写入；校验失败 → `FAILED(VERIFY_FAILED)`。

写入节流：hook 内只更新内存快照（≤ 4 次/秒），落库 1 次/秒，SSE 1 次/秒。

### 8.2 SSE

- 单一长连接 `GET /api/events`（`text/event-stream`），**每 1 秒**推送一条 `snapshot` 事件：

```json
{
  "server_time": 1761...,
  "tasks": [ { "id": "...", "status": "DOWNLOADING", "queue": {"position":1,"cooldown_until":null},
               "progress": {"phase":"video","downloaded_bytes":10485760,"total_bytes":52428800,
                            "percent":20.0,"speed_bps":2411724,"eta_s":18,
                            "streams":[{"kind":"video","percent":20.0},{"kind":"audio","percent":null}]}} ],
  "proxy": {"youtube": {"ok": true, "via": "local"}}
}
```

- 事件只带**当前**快照，不做事件重放：断线重连时 `EventSource` 自动重连，服务端立即发一帧完整快照，前端以快照为准（等价于「恢复任务状态」）。
- 心跳：每 15s 发 `: ping` 注释帧，防中间层断流；响应头带 `Cache-Control: no-cache`、`X-Accel-Buffering: no`。
- 服务端只在有订阅者时聚合；无客户端时任务照常运行（关闭网页不中断）。

---

## 9. 持久化与重启恢复

SQLite（`.data/snapdown.db`，WAL，`busy_timeout=5000`）：

```sql
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,               -- uuid4 hex
  url TEXT NOT NULL,
  platform TEXT NOT NULL,            -- bilibili | douyin | youtube
  route TEXT NOT NULL,               -- direct | proxy
  status TEXT NOT NULL,
  status_reason TEXT,
  title TEXT, duration_s REAL, uploader TEXT,
  options_json TEXT,                 -- 清晰度选项
  selected_option TEXT,
  progress_json TEXT,
  error_code TEXT, error_message TEXT, retryable INTEGER DEFAULT 0,
  work_dir TEXT, output_path TEXT, output_size INTEGER,
  attempts INTEGER DEFAULT 0,
  created_at REAL, updated_at REAL, started_at REAL, finished_at REAL
);
CREATE INDEX idx_tasks_status ON tasks(status);
```

- 启动时：把 `RESOLVE_QUEUED / RESOLVING / DOWNLOAD_QUEUED / DOWNLOADING / MERGING` 全部改为 `INTERRUPTED`，原因「服务重启，任务已中断」；`AWAITING_SELECTION` 保持（等待用户，非运行态）。
- 启动时清理：孤儿进程、超过 `FILE_TTL_HOURS`（默认 24h）的完成文件、超过 7 天的中断工作目录。
- 重试续传：重试复用同一 `work_dir`，yt-dlp `continuedl=True` 自动续传 `.part`（B站按分片、YouTube 按流）。若 `.part` 校验失败则由 yt-dlp 丢弃并重下。

---

## 10. 文件与清理策略

```
.data/work/<task_id>/
   video.f137.mp4 / video.f251.webm / *.part   # 下载中间件
   final.mp4                                    # 合并产物（保留供浏览器下载）
```

| 触发 | 处理 |
|---|---|
| 取消 | 立即删除整个 `work_dir` |
| 失败 | 立即删除整个 `work_dir`（不留无主分片） |
| 中断（重启） | 保留 `work_dir`（供续传），启动时超 7 天再清 |
| 完成 | 删 `.part`/`.ytdl` 等中间件，保留 `final.*`；24h 后清理 |
| 浏览器下载 | `GET /api/tasks/{id}/file` 流式返回，`Content-Disposition: attachment` + RFC5987 中文文件名 |

---

## 11. 安全

- 仅接受白名单平台 URL；拒绝 scheme 非 http(s)、userinfo、IP 字面量、非默认端口。
- 不提供通用 URL 代理/转发接口，杜绝 SSRF 面。
- 文件下载接口用 `Path.resolve()` 校验必须位于该任务 `work_dir` 内，拒绝符号链接与 `..`。
- 输入长度上限 2KB；请求体上限 8KB。
- 代理凭据仅环境变量；日志脱敏。
- 不实现 DRM/会员/登录内容；遇到此类视频直接失败并提示「该视频需要登录或无权限，MVP 不支持」。

---

## 12. API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tasks` | body `{text}`（链接或分享文案）→ 201 `{task}`；同一 URL 已有进行中任务时复用该任务；平台队列满时 429 |
| GET | `/api/tasks` | 快照：非终态任务 + 最近若干终态任务 + 各平台队列 |
| GET | `/api/tasks/{id}` | `{task}` |
| POST | `/api/tasks/{id}/download` | body `{option_id}`：`awaiting_selection` → `download_queued` |
| POST | `/api/tasks/{id}/cancel` | 非终态 → `cancelled`，随后清理工作目录 |
| POST | `/api/tasks/{id}/retry` | `failed` / `cancelled` / `interrupted` → 重新排队（受限频） |
| GET | `/api/tasks/{id}/file` | 成品下载，支持 `Range` 与 `Content-Disposition` |
| GET | `/api/events` | SSE 快照流（整页一条连接，约每秒一帧，10s 心跳） |
| GET | `/api/health` | `{ok, yt_dlp, tools, proxy, platforms, limits, data_dir}` |

任务 DTO（前端唯一数据源，`snake_case`；`can` 由后端算好，前端不猜）：

```json
{
  "id": "…", "url": "…", "platform": "bilibili", "platform_label": "B站",
  "route": "direct", "status": "downloading", "status_label": "下载中", "status_reason": null,
  "title": "…", "duration_s": 154.0, "uploader": "…",
  "options": [{"id": "fmt-30080", "label": "1080P", "detail": "MP4 · 30fps · AVC1",
               "selector": "30080+30280", "height": 1080, "ext": "mp4", "fps": 30,
               "size_bytes": 75497472, "is_best": false}],
  "selected_option": "fmt-30080", "selected_selector": "30080+30280",
  "progress": {"phase": "video", "downloaded_bytes": 0, "total_bytes": null,
               "total_estimated": false, "percent": null, "speed_bps": null, "eta_s": null,
               "streams": [], "updated_at": 0},
  "error": {"code": "PROXY_UNAVAILABLE", "message": "…"},
  "can": {"select": false, "cancel": true, "retry": false, "save": false},
  "retryable": false, "attempts": 1,
  "output_name": "视频标题-xxx.mp4", "output_size": 75497472,
  "queue": {"position": 0, "cooldown_remaining_s": null},
  "created_at": 0, "updated_at": 0, "started_at": 0, "finished_at": null
}
```

错误码（`error.code`）：`INVALID_INPUT` `UNSUPPORTED_PLATFORM` `NOT_FOUND` `CONFLICT` `TOO_MANY_TASKS` `PROXY_UNAVAILABLE` `EXTRACT_FAILED` `DOWNLOAD_FAILED` `INTERRUPTED`（重启时由服务端写入）；HTTP 层另有 `BAD_REQUEST`。`error` 为 `null` 表示无错误；`queue` 仅在排队态下非空。

---

## 13. 前端设计规范（Claude 暖色风）

设计语言：**纸感米白 + 陶土橙**（取自品牌源图 `docs/logo.png` 的配色，源图本地保留、不入库），大面积留白、细边框、极轻阴影、衬线标题 + 无衬线正文、克制的 150–250ms 过渡。

```css
--bg: #F7F3EA;        /* 页面纸感底色 */
--surface: #FFFCF5;   /* 卡片 */
--surface-sunken: #F1EAD9;
--ink: #241F18;       /* 主文字 */
--ink-soft: #5C5445;
--ink-faint: #8C8370;
--line: #E6DDCB;
--accent: #C2542F;    /* 陶土橙，主按钮 */
--accent-hover: #A84525;
--accent-soft: #F6E3D8;
--ok: #3F6B4F; --warn: #A9762A; --danger: #A83A2A;
--radius: 8px / 12px / 18px; --shadow: 0 1px 2px rgba(36,31,24,.05), 0 10px 30px -18px rgba(36,31,24,.35);
```

- 字体：标题 `Georgia, "Songti SC", "Noto Serif SC", serif`；正文 `-apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`。**不加载外部字体**（离线可用、无闪烁）。
- 布局：单列，内容区 `max-width: 940px`（首屏文案 700px），垂直节奏 8/16/24/40；移动端 375px 单列铺满。
- 结构：页头（logo + 名称）→ 输入卡 → 解析结果卡（标题/时长/清晰度单选列表 + 开始下载）→ 任务卡（状态徽标 + 阶段步骤 + 进度条 + 数字/速度/剩余 + 失败原因 + 保存按钮）→ 页脚（`SnapDown Anything · payson`）。
- 首屏：无任务时显示大标题 hero；一旦有任务立即收起，直接进入操作区，避免主按钮被推到首屏之外。
- 清晰度：两列网格，默认项「最佳可用画质」独占整行；窄屏回落单列。
- 操作行：「开始下载」在 ≥761px 且选项多/窗口矮时吸底，主按钮始终可见；窄屏不吸底（卡片本身长，吸底会盖住选项）。
- 最近任务：只渲染最近 1 条结束任务（作为「保存到设备 / 重试」入口），更早记录仍在数据库与磁盘保留，页面折叠为「查看全部 N 条」。
- 状态可视：徽标色区分（等待=灰、进行中=橙、完成=绿、失败=红、取消=灰、中断=黄），文字标签始终存在，不单靠颜色传达。
- 进度条：`role="progressbar"`，`aria-valuenow` 仅在有百分比时设置；未知总大小时显示流式条纹（CSS 动画）+「已下载 12.4 MB · 2.3 MB/s」，`prefers-reduced-motion` 下改为静态。
- 可达性：`aria-live="polite"` 播报状态切换（不播报每次进度跳动）；`:focus-visible` 2px 橙色环；全部可点区域 ≥ 44px；键盘可完成全流程。
- 图标：内联 SVG（Lucide 风格，`stroke-width: 1.75`），不使用 emoji。

---

## 14. 验收标准（逐条可验证）

1. 粘贴 B站/抖音/YouTube 三种链接（含 `b23.tv`、`youtu.be`、抖音分享文案）均能解析出标题、时长、清晰度。
2. 默认选中「最佳可用画质」，可手动切换并生效（下载产物分辨率与所选一致）。
3. 任务在服务端排队；刷新页面、换浏览器标签，队列位置与进度不重置；关闭页面后任务继续。
4. 进度来自 yt-dlp 真实事件：下载量单调递增，速度/ETA 与实际相符；总大小未知时不出现百分比。
5. 音视频分开下载时显示两阶段并可计算总体进度；合并阶段独立显示，未合并完成不显示 100% 完成。
6. 完成后「保存到设备」能下载到本地，文件名正确，`ffprobe` 校验时长与源一致。
7. B站/抖音任务不经过代理（服务端日志可证）；YouTube 任务必须经代理，代理关闭时任务失败且**不**直连（断网/关代理验证）。
8. 同一平台连续提交多个任务，启动间隔 ≥ 冷却时间；刷新/重复点击不能绕过。
9. 取消与失败后 `work_dir` 立即被删除；完成文件 24h 后清理。
10. 服务重启后未完成任务显示「已中断」，重试可复用 `.part` 续传。
11. 非白名单链接（含 IP、file://、随机站点）被拒绝并给出原因。
12. 前端为 Claude 暖色风，375/768/1440 三档无横向滚动，键盘可完整操作。

---

## 15. 风险与假设

| 风险 | 影响 | 应对 |
|---|---|---|
| 抖音反爬（TLS 指纹/风控） | 解析失败 | 先设 UA/Referer；仍失败则评估 `curl-cffi` 模拟指纹（**需单独批准依赖**）；错误明确提示 |
| B站高清需登录 | 1080P+/4K 不可用 | MVP 不传 Cookie，仅提供匿名可用的清晰度，UI 如实列出 |
| YouTube 需 PO token/频繁变更 | 部分视频失败 | 保持 yt-dlp 可升级；失败给出可读原因 |
| 代理仅本机可用 | 他人/服务器部署失效 | `.env` 可配 `PROXY_SERVER` 兜底 |
| 单进程重启丢队列 | 运行中任务中断 | 已设计 `INTERRUPTED` + 续传重试 |
| 磁盘占用 | 大文件堆积 | 完成文件 24h TTL；失败/取消即删 |
| 进度抖动 | 用户困惑 | 只用真实值，不做插值伪造；未知即未知 |

假设：单用户本机使用；只处理用户有权下载的公开内容；不做账号/Cookie/DRM。

---

## 16. 实现记录（截至首版验收）

### 16.1 最终技术选择（用户已确认）

| 项 | 选择 |
|---|---|
| 后端 | Python 3.13 + FastAPI + Uvicorn（yt-dlp 作为库调用，非子进程） |
| 前端 | React 19 + TypeScript + Vite 8，手写 CSS 变量（不引 Tailwind/组件库） |
| 存储 | SQLite（WAL）单文件 + `web/dist` 静态托管，单端口 `127.0.0.1:8787` |
| 依赖 | 项目内 `.venv`：`fastapi`、`uvicorn[standard]`、`yt-dlp`、`pytest`、`httpx` |

### 16.2 已用真实网络验证的路径

| 场景 | 结果 |
|---|---|
| B站 360P / 720P / 1080P（匿名） | 完成，产物 14.7 MB / 51.9 MB / 75.2 MB，ffprobe 时长校验通过 |
| YouTube 480P / 720P（经 127.0.0.1:10808 代理） | 完成（480P 17.5 MB）；`route=proxy`，无直连回退 |
| YouTube 禁止直连 | 代理不可用时任务失败并提示，未发生直连 |
| 抖音分享文案提取 + 平台路由 | 链接成功提取、`platform=douyin`、直连执行 |
| 服务重启 | 运行中任务标 `interrupted`，`retryable=true` |
| 中断后续传 | 重试后首个进度事件 `downloaded_bytes=14,774,561` ≈ 中断前分片 14,767,393，确认复用 `.part` |
| 取消（下载中 21%） | 状态 `cancelled`，工作目录 2.1s 内删除 |
| 同平台并发 | 第二个任务 `download_queued`，`queue.position=1`，冷却读取服务端状态 |
| 文件下载接口 | `206` + `Content-Disposition` + `Range` 支持，可断点续传保存 |

### 16.3 实现中修正的问题（都有对应测试或实测）

1. **直连平台被系统代理劫持**：Windows 系统代理（10808）会让 B站 下载随机 503。修复：`app/ytdlp_runner.py` 中 `opts["proxy"] = proxy or ""`，直连路由显式写入空代理。实测修复后 B站 1080P 完成。
2. **取消后残留文件删不掉**：根因是 `TaskCancelled` 的 traceback 帧仍引用 yt-dlp 文件对象（Windows 独占句柄）。修复：捕获处清空 `exc.__traceback__`，并由独立 janitor 任务在下载线程结束后 `gc.collect()` + 重试删除，实测 2.1s 清理完成。
3. **代理健康检查误判**：探测端口与「有候选代理」解耦，`/api/health` 增加 `proxy.selected`。
4. **B站 CDN 临时 503**：`_clean_error` 把 503/429 转成「平台临时限流，请稍后重试」，避免把 yt-dlp 原文直接抛给用户。

### 16.4 已知限制（如实记录）

- **抖音未做真实端到端下载**：缺少有效分享短链样本；伪造 `v.douyin.com` 链接按 yt-dlp 行为返回「暂不支持该链接类型」。代码路径与 B站共用，风险点为平台风控。
- **YouTube 缺 JS runtime**：日志提示 `No supported JavaScript runtime ... Only deno is enabled`。当前节点未装 Deno，部分格式可能缺失；如需完整格式，安装 Deno 后 yt-dlp 自动启用。
- **B站连续高频请求会触发 CDN 503**：属平台侧限流，服务端按平台冷却 3s，仍可能在批量测试时出现。
- 单进程内取消依赖 yt-dlp 进度回调，最坏等待一个网络超时（`socket_timeout=10`）。

---
