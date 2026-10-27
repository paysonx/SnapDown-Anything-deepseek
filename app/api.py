"""HTTP 接口：任务创建、清晰度选择、取消、重试、SSE 进度、文件保存、健康检查。"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .errors import NotFound
from .models import PLATFORM_LABELS, PLATFORM_ROUTES, TaskStatus
from .security import ensure_inside

router = APIRouter(prefix="/api")

_ILLEGAL_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


class CreateTaskIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class DownloadIn(BaseModel):
    option_id: str = Field(min_length=1, max_length=80)


def _manager(request: Request):
    return request.app.state.manager


def _sse(payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: snapshot\ndata: {body}\n\n"


# -- 任务 ----------------------------------------------------------------
@router.post("/tasks", status_code=201)
async def create_task(payload: CreateTaskIn, request: Request) -> dict:
    manager = _manager(request)
    task = manager.create_task(payload.text)
    return {"task": manager.task_payload(task)}


@router.get("/tasks")
async def list_tasks(request: Request) -> dict:
    return _manager(request).build_snapshot()


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict:
    manager = _manager(request)
    return {"task": manager.task_payload(manager.get(task_id))}


@router.post("/tasks/{task_id}/download")
async def start_download(task_id: str, payload: DownloadIn, request: Request) -> dict:
    manager = _manager(request)
    task = await manager.start_download(task_id, payload.option_id)
    return {"task": manager.task_payload(task)}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> dict:
    manager = _manager(request)
    task = await manager.cancel(task_id)
    return {"task": manager.task_payload(task)}


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, request: Request) -> dict:
    manager = _manager(request)
    task = await manager.retry(task_id)
    return {"task": manager.task_payload(task)}


@router.get("/tasks/{task_id}/file")
async def download_file(task_id: str, request: Request) -> FileResponse:
    manager = _manager(request)
    task = manager.get(task_id)
    if task.status is not TaskStatus.COMPLETED or not task.output_path or not task.work_dir:
        raise NotFound("该任务还没有可保存的文件")

    path = ensure_inside(Path(task.work_dir), Path(task.output_path))
    if not path.exists() or path.stat().st_size <= 0:
        raise NotFound("文件已被清理或已过期，请重新下载")

    title = _ILLEGAL_FILENAME.sub("_", (task.title or "video")).strip(" .")[:80] or "video"
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"{title}{path.suffix or '.mp4'}",
    )


# -- 进度推送 ------------------------------------------------------------
@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    manager = _manager(request)
    hub = manager.hub
    queue = hub.subscribe()

    async def stream():
        try:
            yield "retry: 2000\n\n"
            yield _sse(manager.build_snapshot())
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=10)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield _sse(payload)
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# -- 健康检查 ------------------------------------------------------------
@router.get("/health")
async def health(request: Request) -> dict:
    manager = _manager(request)
    tools = await asyncio.to_thread(manager.downloader.tools_status)
    proxy = await manager.proxies.status()
    try:
        from yt_dlp.version import __version__ as yt_dlp_version
    except Exception:  # pragma: no cover
        yt_dlp_version = "unknown"

    return {
        "ok": True,
        "yt_dlp": yt_dlp_version,
        "tools": tools,
        "proxy": proxy,
        "platforms": {
            platform.value: {
                "label": PLATFORM_LABELS[platform],
                "route": PLATFORM_ROUTES[platform].value,
            }
            for platform in manager.lanes
        },
        "limits": {
            "max_active_tasks": manager.settings.max_active_tasks,
            "file_ttl_hours": manager.settings.file_ttl_hours,
            "cooldowns": {key.value: lane.cooldown for key, lane in manager.lanes.items()},
        },
        "data_dir": str(manager.settings.data_dir),
    }
