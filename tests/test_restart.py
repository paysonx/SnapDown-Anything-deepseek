"""服务重启：运行中的任务标记「已中断」，重试复用任务目录续传。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Platform, QualityOption, Task, TaskStatus
from app.store import Store
from tests.conftest import FakeDownloader, wait_for

BILI = "https://www.bilibili.com/video/BV1GJ411x7h7"


def _seed(settings: Settings, *, status: TaskStatus) -> tuple[str, Path]:
    store = Store(settings.db_path)
    store.init()
    work_dir = settings.work_dir / f"seed-{status.value}"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "video.mp4.part").write_bytes(b"partial")

    task = Task.new(BILI, Platform.BILIBILI, str(work_dir))
    task.title = "断点任务"
    task.options = [
        QualityOption(
            id="best",
            label="最佳可用画质",
            detail="自动选择最高分辨率与最佳音轨",
            selector="bestvideo*+bestaudio/best",
            is_best=True,
        )
    ]
    task.selected_option = "best"
    task.status = status
    task.attempts = 1
    store.create(task)
    return task.id, work_dir


def test_restart_marks_running_task_interrupted(settings):
    task_id, _ = _seed(settings, status=TaskStatus.DOWNLOADING)
    with TestClient(create_app(settings, downloader=FakeDownloader())) as client:
        task = client.get(f"/api/tasks/{task_id}").json()["task"]
        assert task["status"] == "interrupted"
        assert task["status_label"] == "已中断"
        assert task["can"]["retry"] is True


def test_restart_keeps_completed_tasks(settings):
    task_id, work_dir = _seed(settings, status=TaskStatus.COMPLETED)
    with TestClient(create_app(settings, downloader=FakeDownloader())) as client:
        task = client.get(f"/api/tasks/{task_id}").json()["task"]
        assert task["status"] == "completed"
        assert task["can"]["retry"] is False


def test_retry_after_restart_resumes_download(settings):
    task_id, work_dir = _seed(settings, status=TaskStatus.DOWNLOADING)
    with TestClient(create_app(settings, downloader=FakeDownloader(size=4096))) as client:
        assert client.get(f"/api/tasks/{task_id}").json()["task"]["status"] == "interrupted"

        response = client.post(f"/api/tasks/{task_id}/retry")
        assert response.status_code == 200

        task = wait_for(client, task_id, {"completed"})
        assert task["output_size"] == 4096
        assert (work_dir / "video.mp4").exists()
        # 合并成功后残留的 .part 分片会被清理
        assert not (work_dir / "video.mp4.part").exists()
