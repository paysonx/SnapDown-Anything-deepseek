"""平台通道：每平台并发 1 + 冷却。

限频状态只存在于服务端进程内，刷新页面、重复点击都无法绕过；
解析、下载、重试共用同一通道与同一份冷却额度。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .errors import TaskCancelled


class PlatformLane:
    def __init__(self, platform: str, cooldown: float) -> None:
        self.platform = platform
        self.cooldown = max(0.0, float(cooldown))
        self._waiters: list[str] = []
        self._running: str | None = None
        self._next_start = 0.0
        self._cond = asyncio.Condition()

    @property
    def running(self) -> str | None:
        return self._running

    @property
    def queued(self) -> list[str]:
        return list(self._waiters)

    def cooldown_remaining(self) -> float:
        return max(0.0, self._next_start - time.monotonic())

    async def acquire(self, task_id: str, cancel: asyncio.Event) -> None:
        """排队等待本平台通道；期间可被取消。"""
        async with self._cond:
            if task_id not in self._waiters:
                self._waiters.append(task_id)
            self._cond.notify_all()
            try:
                while True:
                    if cancel.is_set():
                        raise TaskCancelled()
                    now = time.monotonic()
                    if self._waiters and self._waiters[0] == task_id:
                        if self._running is None and now >= self._next_start:
                            self._waiters.pop(0)
                            self._running = task_id
                            self._cond.notify_all()
                            return
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=0.25)
                    except asyncio.TimeoutError:
                        continue
            except TaskCancelled:
                if task_id in self._waiters:
                    self._waiters.remove(task_id)
                self._cond.notify_all()
                raise

    async def release(self) -> None:
        async with self._cond:
            self._running = None
            self._next_start = time.monotonic() + self.cooldown
            self._cond.notify_all()

    def describe(self, task_id: str) -> dict[str, Any] | None:
        """给前端的队列信息：位置、冷却、能否估算开始时间。"""
        if self._running == task_id:
            return {
                "state": "running",
                "position": 0,
                "queue_size": len(self._waiters),
                "cooldown_seconds": self.cooldown,
                "cooldown_until": None,
                "eta_start_s": 0,
            }
        if task_id in self._waiters:
            index = self._waiters.index(task_id)
            cooldown = self.cooldown_remaining()
            # 只有队首才能给出确定的开始时间；其余位置依赖前序任务耗时，不做估算
            eta = round(cooldown, 1) if index == 0 else None
            return {
                "state": "queued",
                "position": index + 1,
                "queue_size": len(self._waiters),
                "cooldown_seconds": self.cooldown,
                "cooldown_until": round(time.time() + cooldown, 3),
                "eta_start_s": eta,
            }
        return None

    def snapshot(self) -> dict[str, Any]:
        cooldown = self.cooldown_remaining()
        return {
            "platform": self.platform,
            "running": self._running is not None,
            "queued": len(self._waiters),
            "cooldown_seconds": self.cooldown,
            "cooldown_remaining_s": round(cooldown, 1),
            "cooldown_until": round(time.time() + cooldown, 3) if cooldown > 0 else None,
        }

    # -- 测试辅助 ----------------------------------------------------------
    def reset(self) -> None:
        self._waiters.clear()
        self._running = None
        self._next_start = 0.0
