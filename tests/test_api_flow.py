"""端到端接口流程：解析 → 选择 → 下载 → 保存，以及取消、失败、限频、SSE。"""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.proxy import ProxyManager
from tests.conftest import FakeDownloader, wait_for

BILI = "https://www.bilibili.com/video/BV1GJ411x7h7"
BILI2 = "https://www.bilibili.com/video/BV1xx411c7mD"
YOUTUBE = "https://youtu.be/dQw4w9WgXcQ"
LOCAL_PROXY = "http://127.0.0.1:10808"


def test_full_download_flow(client_factory):
    downloader = FakeDownloader(size=8192)
    with client_factory(downloader) as client:
        response = client.post("/api/tasks", json={"text": f"看这个 {BILI}?spm_id_from=333.999"})
        assert response.status_code == 201
        task = response.json()["task"]
        task_id = task["id"]
        assert task["platform"] == "bilibili"
        assert task["route"] == "direct"
        assert task["status"] == "resolve_queued"
        assert task["status_label"] == "等待解析"

        task = wait_for(client, task_id, {"awaiting_selection"})
        assert task["title"] == "测试视频"
        assert task["duration_s"] == 62.0
        assert task["options"][0]["id"] == "best"
        assert task["selected_option"] == "best"

        response = client.post(f"/api/tasks/{task_id}/download", json={"option_id": "fmt-137"})
        assert response.status_code == 200
        assert response.json()["task"]["status"] == "download_queued"

        task = wait_for(client, task_id, {"completed"})
        assert task["output_name"] == "video.mp4"
        assert task["output_size"] == 8192
        assert task["error"] is None
        assert task["can"]["save"] is True
        assert downloader.last_selector == "137+bestaudio/best"

        response = client.get(f"/api/tasks/{task_id}/file")
        assert response.status_code == 200
        assert len(response.content) == 8192
        assert "attachment" in response.headers["content-disposition"]


def test_domestic_platform_never_uses_proxy(client_factory):
    downloader = FakeDownloader()
    with client_factory(downloader) as client:
        task = client.post("/api/tasks", json={"text": BILI}).json()["task"]
        wait_for(client, task["id"], {"awaiting_selection"})
        assert downloader.last_proxy is None


def test_youtube_requires_proxy(settings):
    with TestClient(create_app(settings, downloader=FakeDownloader())) as client:
        response = client.post("/api/tasks", json={"text": YOUTUBE})
        assert response.status_code == 503
        body = response.json()["error"]
        assert body["code"] == "PROXY_UNAVAILABLE"
        assert "YouTube" in body["message"]


def test_youtube_uses_configured_proxy(settings, monkeypatch):
    monkeypatch.setattr(ProxyManager, "_probe_blocking", lambda self, url: True)
    proxied = replace(settings, proxy_mode="local", proxy_local=LOCAL_PROXY)
    downloader = FakeDownloader()
    with TestClient(create_app(proxied, downloader=downloader)) as client:
        task = client.post("/api/tasks", json={"text": YOUTUBE}).json()["task"]
        assert task["route"] == "proxy"
        wait_for(client, task["id"], {"awaiting_selection"})
        assert downloader.last_proxy == LOCAL_PROXY


def test_cancel_download_cleans_work_dir(client_factory):
    downloader = FakeDownloader(steps=60, step_delay=0.02)
    with client_factory(downloader) as client:
        task = client.post("/api/tasks", json={"text": BILI}).json()["task"]
        task = wait_for(client, task["id"], {"awaiting_selection"})
        client.post(f"/api/tasks/{task['id']}/download", json={"option_id": "best"})
        wait_for(client, task["id"], {"downloading"})

        response = client.post(f"/api/tasks/{task['id']}/cancel")
        assert response.status_code == 200
        task = wait_for(client, task["id"], {"cancelled"})
        assert task["can"]["retry"] is True

        work_dir = client.app.state.settings.work_dir / task["id"]
        deadline = time.monotonic() + 5
        while work_dir.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not work_dir.exists()


def test_resolve_failure_is_reported_and_retryable(client_factory):
    downloader = FakeDownloader(fail_on="resolve")
    with client_factory(downloader) as client:
        task = client.post("/api/tasks", json={"text": BILI}).json()["task"]
        task = wait_for(client, task["id"], {"failed"})
        assert task["error"]["code"] == "EXTRACT_FAILED"
        assert task["retryable"] is True
        assert task["can"]["retry"] is True
        assert "解析失败" in task["status_reason"]

        downloader.fail_on = None
        response = client.post(f"/api/tasks/{task['id']}/retry")
        assert response.status_code == 200
        task = wait_for(client, task["id"], {"awaiting_selection"})
        assert task["error"] is None


def test_invalid_and_unsupported_input(client_factory):
    with client_factory(FakeDownloader()) as client:
        response = client.post("/api/tasks", json={"text": "没有链接"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_INPUT"

        response = client.post("/api/tasks", json={"text": "https://vimeo.com/123"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UNSUPPORTED_PLATFORM"

        response = client.post("/api/tasks", json={"text": ""})
        assert response.status_code == 400


def test_duplicate_submit_reuses_running_task(client_factory):
    with client_factory(FakeDownloader(resolve_delay=0.2)) as client:
        first = client.post("/api/tasks", json={"text": BILI}).json()["task"]
        second = client.post("/api/tasks", json={"text": BILI}).json()["task"]
        assert first["id"] == second["id"]


def test_active_task_limit_returns_429(settings):
    app = create_app(
        replace(settings, max_active_tasks=1),
        downloader=FakeDownloader(resolve_delay=0.5),
    )
    with TestClient(app) as client:
        assert client.post("/api/tasks", json={"text": BILI}).status_code == 201
        response = client.post("/api/tasks", json={"text": BILI2})
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "TOO_MANY_TASKS"


def test_sse_stream_starts_with_snapshot(client_factory):
    with client_factory(FakeDownloader()) as client:
        with client.stream("GET", "/api/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = response.iter_lines()
            assert next(lines) == "retry: 2000"
            line = next(lines)
            while line == "":
                line = next(lines)
            assert line == "event: snapshot"
            data = next(lines)
            assert data.startswith("data: ")
            payload = json.loads(data[len("data: "):])
            assert payload["type"] == "snapshot"
            assert "tasks" in payload
            assert set(payload["platforms"]) == {"bilibili", "douyin", "youtube"}


def test_health_reports_tools_and_proxy(client_factory):
    with client_factory(FakeDownloader()) as client:
        payload = client.get("/api/health").json()
        assert payload["ok"] is True
        assert payload["tools"]["ffmpeg"] is True
        assert "candidates" in payload["proxy"]
        assert payload["platforms"]["youtube"]["route"] == "proxy"
