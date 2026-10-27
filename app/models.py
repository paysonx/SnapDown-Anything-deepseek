"""领域模型：平台、状态机、清晰度选项、任务与进度。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Platform(str, Enum):
    BILIBILI = "bilibili"
    DOUYIN = "douyin"
    YOUTUBE = "youtube"


class Route(str, Enum):
    DIRECT = "direct"
    PROXY = "proxy"


PLATFORM_LABELS: dict[Platform, str] = {
    Platform.BILIBILI: "B站",
    Platform.DOUYIN: "抖音",
    Platform.YOUTUBE: "YouTube",
}

# 网络规则由后端强制：国内平台只直连，YouTube 只走代理。
PLATFORM_ROUTES: dict[Platform, Route] = {
    Platform.BILIBILI: Route.DIRECT,
    Platform.DOUYIN: Route.DIRECT,
    Platform.YOUTUBE: Route.PROXY,
}


class TaskStatus(str, Enum):
    RESOLVE_QUEUED = "resolve_queued"
    RESOLVING = "resolving"
    AWAITING_SELECTION = "awaiting_selection"
    DOWNLOAD_QUEUED = "download_queued"
    DOWNLOADING = "downloading"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


STATUS_LABELS: dict[TaskStatus, str] = {
    TaskStatus.RESOLVE_QUEUED: "等待解析",
    TaskStatus.RESOLVING: "解析中",
    TaskStatus.AWAITING_SELECTION: "选择清晰度",
    TaskStatus.DOWNLOAD_QUEUED: "等待下载",
    TaskStatus.DOWNLOADING: "下载中",
    TaskStatus.MERGING: "合并中",
    TaskStatus.COMPLETED: "已完成",
    TaskStatus.FAILED: "失败",
    TaskStatus.CANCELLED: "已取消",
    TaskStatus.INTERRUPTED: "已中断",
}

# 占用平台通道或正在进行的工作状态
ACTIVE_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.RESOLVE_QUEUED,
        TaskStatus.RESOLVING,
        TaskStatus.DOWNLOAD_QUEUED,
        TaskStatus.DOWNLOADING,
        TaskStatus.MERGING,
    }
)

# 服务重启后需要标记为「已中断」的状态
RUNNING_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.RESOLVE_QUEUED,
        TaskStatus.RESOLVING,
        TaskStatus.DOWNLOAD_QUEUED,
        TaskStatus.DOWNLOADING,
        TaskStatus.MERGING,
    }
)

TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.INTERRUPTED,
    }
)

RETRYABLE_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.FAILED, TaskStatus.INTERRUPTED, TaskStatus.CANCELLED}
)


@dataclass
class QualityOption:
    """一个可选清晰度。selector 是交给 yt-dlp 的 format 字符串。"""

    id: str
    label: str
    detail: str
    selector: str
    height: int | None = None
    ext: str | None = None
    fps: float | None = None
    size_bytes: int | None = None
    is_best: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "detail": self.detail,
            "selector": self.selector,
            "height": self.height,
            "ext": self.ext,
            "fps": self.fps,
            "size_bytes": self.size_bytes,
            "is_best": self.is_best,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "QualityOption":
        return cls(
            id=str(raw["id"]),
            label=str(raw.get("label") or ""),
            detail=str(raw.get("detail") or ""),
            selector=str(raw.get("selector") or "best"),
            height=raw.get("height"),
            ext=raw.get("ext"),
            fps=raw.get("fps"),
            size_bytes=raw.get("size_bytes"),
            is_best=bool(raw.get("is_best")),
        )


@dataclass
class Progress:
    """对前端展示的进度快照。百分比未知时为 None，禁止编造。"""

    phase: str | None = None  # video | audio | single | merging
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    total_estimated: bool = False
    percent: float | None = None
    speed_bps: float | None = None
    eta_s: int | None = None
    streams: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "total_estimated": self.total_estimated,
            "percent": self.percent,
            "speed_bps": self.speed_bps,
            "eta_s": self.eta_s,
            "streams": self.streams,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "Progress":
        raw = raw or {}
        return cls(
            phase=raw.get("phase"),
            downloaded_bytes=int(raw.get("downloaded_bytes") or 0),
            total_bytes=raw.get("total_bytes"),
            total_estimated=bool(raw.get("total_estimated")),
            percent=raw.get("percent"),
            speed_bps=raw.get("speed_bps"),
            eta_s=raw.get("eta_s"),
            streams=list(raw.get("streams") or []),
            updated_at=float(raw.get("updated_at") or 0.0),
        )


@dataclass
class Task:
    id: str
    url: str
    platform: Platform
    route: Route
    status: TaskStatus
    status_reason: str | None = None
    title: str | None = None
    duration_s: float | None = None
    uploader: str | None = None
    options: list[QualityOption] = field(default_factory=list)
    selected_option: str | None = None
    progress: Progress = field(default_factory=Progress)
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    work_dir: str | None = None
    output_path: str | None = None
    output_size: int | None = None
    attempts: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    @classmethod
    def new(cls, url: str, platform: Platform, work_dir: str) -> "Task":
        return cls(
            id=uuid.uuid4().hex,
            url=url,
            platform=platform,
            route=PLATFORM_ROUTES[platform],
            status=TaskStatus.RESOLVE_QUEUED,
            status_reason="排队等待解析",
            work_dir=work_dir,
        )

    def selected(self) -> QualityOption | None:
        for option in self.options:
            if option.id == self.selected_option:
                return option
        return None

    def to_api(self, queue: dict[str, Any] | None = None) -> dict[str, Any]:
        option = self.selected()
        return {
            "id": self.id,
            "url": self.url,
            "platform": self.platform.value,
            "platform_label": PLATFORM_LABELS[self.platform],
            "route": self.route.value,
            "status": self.status.value,
            "status_label": STATUS_LABELS[self.status],
            "status_reason": self.status_reason,
            "title": self.title,
            "duration_s": self.duration_s,
            "uploader": self.uploader,
            "options": [item.to_dict() for item in self.options],
            "selected_option": self.selected_option,
            "selected_selector": option.selector if option else None,
            "progress": self.progress.to_dict(),
            "error": (
                {"code": self.error_code, "message": self.error_message}
                if self.error_code
                else None
            ),
            "can": {
                "select": self.status is TaskStatus.AWAITING_SELECTION and bool(self.options),
                "cancel": self.status in ACTIVE_STATUSES or self.status is TaskStatus.AWAITING_SELECTION,
                "retry": self.status in RETRYABLE_STATUSES,
                "save": self.status is TaskStatus.COMPLETED and bool(self.output_path),
            },
            "retryable": self.retryable,
            "output_name": self.output_name(),
            "output_size": self.output_size,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "queue": queue,
        }

    def output_name(self) -> str | None:
        if not self.output_path:
            return None
        from pathlib import Path

        return Path(self.output_path).name
