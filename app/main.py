"""FastAPI 入口：装配依赖、托管前端产物、优雅启停、统一错误响应。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import Settings, get_settings
from .errors import AppError
from .events import EventHub
from .jobs import TaskManager
from .proxy import ProxyManager
from .store import Store
from .ytdlp_runner import YtDlpDownloader

log = logging.getLogger("app")


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_snapped", False) for handler in root.handlers):
        return
    root.setLevel(settings.log_level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console._snapped = True  # type: ignore[attr-defined]
    root.addHandler(console)

    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.data_dir / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._snapped = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
    except OSError:
        log.warning("无法写入日志文件，仅使用控制台日志")


def create_app(
    settings: Settings | None = None,
    *,
    downloader: Any | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.work_dir.mkdir(parents=True, exist_ok=True)

        store = Store(settings.db_path)
        store.init()
        hub = EventHub()
        proxies = ProxyManager(settings)
        yt_downloader = downloader or YtDlpDownloader(settings)
        manager = TaskManager(settings, store, yt_downloader, proxies, hub)

        app.state.settings = settings
        app.state.manager = manager
        app.state.hub = hub

        tools = yt_downloader.tools_status()
        if not tools.get("ffmpeg"):
            log.warning("未检测到 ffmpeg：B站/YouTube 的音视频合并会失败，请先安装 ffmpeg")
        if not tools.get("ffprobe"):
            log.warning("未检测到 ffprobe：成品校验将退化为文件大小校验")

        await manager.start()
        log.info("服务已启动：http://%s:%s", settings.host, settings.port)
        try:
            yield
        finally:
            await manager.stop()
            log.info("服务已停止")

    app = FastAPI(
        title="SnapDown Anything",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.dev_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(item) for item in first.get("loc", [])[1:]) or "请求"
        message = first.get("msg", "参数不合法")
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_INPUT",
                    "message": f"{field} 不合法：{message}",
                    "retryable": False,
                }
            },
            status_code=400,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("未处理异常：%s %s", request.method, request.url.path)
        return JSONResponse(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "服务内部错误，请查看后端日志",
                    "retryable": True,
                }
            },
            status_code=500,
        )

    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = settings.web_dist
    index = dist / "index.html"
    if not index.exists():

        @app.get("/", include_in_schema=False)
        async def frontend_missing() -> JSONResponse:
            return JSONResponse(
                {
                    "message": "前端尚未构建。请进入 web/ 执行 pnpm install && pnpm build，"
                    "或使用 pnpm dev 启动开发服务器（http://127.0.0.1:5173）。",
                    "api": "/api/health",
                }
            )

        return

    # 单页应用：静态产物由后端直接托管，生产环境只暴露 8787 一个端口
    app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")


app = create_app()
