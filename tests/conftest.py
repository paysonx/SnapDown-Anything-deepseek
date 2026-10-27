"""测试夹具：临时数据目录、离线假下载器、带生命周期的测试客户端。"""

from __future__ import annotations

import asyncio
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.errors import AppError, TaskCancelled  # noqa: E402
from app.ytdlp_runner import DownloadResult, ResolveResult, build_quality_options  # noqa: E402

FAKE_FORMATS: list[dict[str, Any]] = [
    {
        "format_id": "137",
        "height": 1080,
        "fps": 30,
        "ext": "mp4",
        "vcodec": "avc1.640028",
        "acodec": "none",
        "filesize": 800,
        "tbr": 4000,
    },
    {
        "format_id": "140",
        "height": 0,
        "ext": "m4a",
        "vcodec": "none",
        "acodec": "mp4a.40.2",
        "filesize": 200,
        "tbr": 128,
    },
    {
        "format_id": "18",
        "height": 360,
        "ext": "mp4",
        "vcodec": "avc1.42001E",
        "acodec": "mp4a.40.2",
        "filesize": 300,
        "tbr": 500,
    },
]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        web_dist=tmp_path / "web-dist",
        cooldowns={"bilibili": 0.01, "douyin": 0.01, "youtube": 0.01},
        proxy_mode="off",
    )


class FakeDownloader:
    """不联网的假 yt-dlp，用于验证编排、进度、取消与文件交付。"""

    def __init__(
        self,
        *,
        size: int = 4096,
        steps: int = 4,
        step_delay: float = 0.0,
        resolve_delay: float = 0.0,
        fail_on: str | None = None,
    ) -> None:
        self.size = size
        self.steps = steps
        self.step_delay = step_delay
        self.resolve_delay = resolve_delay
        self.fail_on = fail_on
        self.resolve_calls = 0
        self.download_calls = 0
        self.last_selector: str | None = None
        self.last_proxy: str | None = None

    def tools_status(self) -> dict[str, Any]:
        return {
            "ffmpeg": True,
            "ffprobe": True,
            "ffmpeg_path": "ffmpeg",
            "ffprobe_path": "ffprobe",
        }

    async def resolve(self, url: str, proxy: str | None) -> ResolveResult:
        self.resolve_calls += 1
        self.last_proxy = proxy
        await asyncio.sleep(self.resolve_delay)
        if self.fail_on == "resolve":
            raise AppError("解析失败：测试注入", code="EXTRACT_FAILED", retryable=True)
        options = build_quality_options({"formats": FAKE_FORMATS})
        return ResolveResult(
            title="测试视频", duration_s=62.0, uploader="tester", options=options
        )

    async def download(
        self,
        *,
        url: str,
        selector: str,
        work_dir: Path,
        proxy: str | None,
        cancel: asyncio.Event,
        on_progress: Any,
        on_merge: Any,
    ) -> DownloadResult:
        self.download_calls += 1
        self.last_selector = selector
        self.last_proxy = proxy
        await asyncio.sleep(0)
        if self.fail_on == "download":
            raise AppError("下载失败：测试注入", code="DOWNLOAD_FAILED", retryable=True)

        work_dir.mkdir(parents=True, exist_ok=True)
        target = work_dir / "video.mp4"
        total = self.size
        step = max(1, total // max(1, self.steps))
        done = 0
        while done < total:
            if cancel.is_set():
                raise TaskCancelled()
            done = min(total, done + step)
            on_progress(
                {
                    "status": "downloading",
                    "downloaded_bytes": done,
                    "total_bytes": total,
                    "speed": 1024.0 * 512,
                    "eta": 3,
                    "info_dict": {
                        "format_id": "137",
                        "vcodec": "avc1.640028",
                        "acodec": "none",
                        "ext": "mp4",
                    },
                }
            )
            await asyncio.sleep(self.step_delay)

        on_merge({"status": "started", "postprocessor": "Merger"})
        await asyncio.sleep(0)
        target.write_bytes(b"x" * total)
        on_merge({"status": "finished", "postprocessor": "Merger"})
        return DownloadResult(output_path=target, size=total, duration_s=62.0)


@pytest.fixture
def client_factory(settings: Settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    @contextmanager
    def _make(downloader: Any | None = None) -> Iterator[TestClient]:
        app = create_app(settings, downloader=downloader or FakeDownloader())
        with TestClient(app) as client:
            yield client

    return _make


def wait_for(
    client: Any, task_id: str, statuses: set[str], timeout: float = 8.0
) -> dict[str, Any]:
    """轮询任务状态，直到进入目标状态或超时。"""
    deadline = time.monotonic() + timeout
    payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        payload = client.get(f"/api/tasks/{task_id}").json()["task"]
        if payload["status"] in statuses:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"等待状态 {statuses} 超时，当前状态：{payload.get('status')}")
