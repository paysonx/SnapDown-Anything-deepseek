"""平台通道：并发 1 + 冷却，排队可取消。"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.errors import TaskCancelled
from app.limiter import PlatformLane


def test_single_flight_and_cooldown_between_starts():
    async def scenario() -> list[tuple[str, float]]:
        lane = PlatformLane("bilibili", 0.15)
        cancel = asyncio.Event()
        timeline: list[tuple[str, float]] = []

        async def worker(name: str) -> None:
            await lane.acquire(name, cancel)
            timeline.append((name, time.monotonic()))
            await asyncio.sleep(0.02)
            await lane.release()

        await asyncio.gather(worker("a"), worker("b"))
        return timeline

    timeline = asyncio.run(scenario())
    assert [name for name, _ in timeline] == ["a", "b"]
    assert timeline[1][1] - timeline[0][1] >= 0.14


def test_queue_position_is_reported():
    async def scenario():
        lane = PlatformLane("douyin", 0.5)
        cancel = asyncio.Event()
        await lane.acquire("a", cancel)
        waiter = asyncio.create_task(lane.acquire("b", cancel))
        await asyncio.sleep(0.05)
        info = lane.describe("b")
        assert info is not None
        assert info["state"] == "queued"
        assert info["position"] == 1
        assert info["eta_start_s"] is not None
        cancel.set()
        with pytest.raises(TaskCancelled):
            await waiter
        assert lane.queued == []
        await lane.release()

    asyncio.run(scenario())


def test_running_task_is_not_queued():
    async def scenario():
        lane = PlatformLane("youtube", 0.0)
        cancel = asyncio.Event()
        await lane.acquire("a", cancel)
        info = lane.describe("a")
        assert info is not None and info["state"] == "running"
        await lane.release()

    asyncio.run(scenario())
