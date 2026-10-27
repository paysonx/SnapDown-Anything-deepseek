"""任务编排：状态流转、平台通道、代理选择、进度、取消、重试、清理、恢复。"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import (
    AppError,
    Conflict,
    InvalidInput,
    NotFound,
    ProxyUnavailable,
    TaskCancelled,
    TooManyTasks,
)
from .events import EventHub
from .limiter import PlatformLane
from .models import (
    ACTIVE_STATUSES,
    Platform,
    Progress,
    RETRYABLE_STATUSES,
    TERMINAL_STATUSES,
    Task,
    TaskStatus,
)
from .progress import ProgressTracker
from .proxy import ProxyManager
from .security import validate_task_input
from .store import Store
from .ytdlp_runner import TEMP_SUFFIXES, YtDlpDownloader

log = logging.getLogger(__name__)

RECENT_TERMINAL_LIMIT = 8


class TaskManager:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        downloader: YtDlpDownloader,
        proxies: ProxyManager,
        hub: EventHub,
    ) -> None:
        self.settings = settings
        self.store = store
        self.downloader = downloader
        self.proxies = proxies
        self.hub = hub
        self.lanes: dict[Platform, PlatformLane] = {
            platform: PlatformLane(platform.value, settings.cooldown_for(platform.value))
            for platform in Platform
        }
        self._progress: dict[str, Progress] = {}
        self._persisted: dict[str, float] = {}
        self._cancel: dict[str, asyncio.Event] = {}
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._janitor: set[asyncio.Task[None]] = set()
        self._ticker: asyncio.Task[None] | None = None
        self._proxy_status: dict[str, Any] = {
            "mode": settings.proxy_mode,
            "candidates": [],
            "selected": None,
            "available": None,
        }

    # -- 生命周期 ----------------------------------------------------------
    async def start(self) -> None:
        interrupted = self.store.mark_interrupted(
            "服务异常重启，任务已中断，可重试（已下载分片会尽量复用）"
        )
        if interrupted:
            log.warning("已将 %s 个未完成任务标记为已中断", interrupted)
        await asyncio.to_thread(self._cleanup_expired)
        self._proxy_status = await self.proxies.status()
        self._ticker = asyncio.create_task(self._tick(), name="task-ticker")

    async def stop(self) -> None:
        if self._ticker is not None:
            self._ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ticker
            self._ticker = None
        for event in self._cancel.values():
            event.set()
        pending = [job for job in self._jobs.values() if not job.done()]
        if pending:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True), timeout=3
                )
        self.store.mark_interrupted("服务关闭，任务已中断，可重试")

    # -- 对外操作 ----------------------------------------------------------
    def get(self, task_id: str) -> Task:
        task = self.store.get(task_id)
        if task is None:
            raise NotFound("任务不存在")
        return task

    def task_payload(self, task: Task) -> dict[str, Any]:
        return task.to_api(self._queue_info(task))

    def create_task(self, text: str) -> Task:
        url, platform = validate_task_input(text, max_chars=self.settings.max_input_chars)

        existing = self.store.find_active_by_url(url)
        if existing is not None:
            # 重复点击/刷新页面后重复提交：直接复用进行中的任务
            return existing

        if self.store.count_active() >= self.settings.max_active_tasks:
            raise TooManyTasks(
                f"同时进行的任务已达上限（{self.settings.max_active_tasks} 个），请等任务结束后再试"
            )

        if platform is Platform.YOUTUBE and not self.proxies.has_candidates():
            raise ProxyUnavailable(
                "未配置可用代理：YouTube 只允许通过代理访问，不会回退直连。"
                "请先在 .env 中配置 PROXY_LOCAL 或 PROXY_SERVER。"
            )

        task = Task.new(url, platform, "")
        task.work_dir = str(self.settings.work_dir / task.id)
        self.store.create(task)
        self._spawn(task.id, self._run_resolve(task.id))
        return task

    async def start_download(self, task_id: str, option_id: str) -> Task:
        task = self.get(task_id)
        if task.status is not TaskStatus.AWAITING_SELECTION:
            raise Conflict("当前状态不能开始下载")
        option = next((item for item in task.options if item.id == option_id), None)
        if option is None:
            raise InvalidInput("清晰度选项不存在，请重新解析")

        self._patch(
            task_id,
            selected_option=option.id,
            status=TaskStatus.DOWNLOAD_QUEUED,
            status_reason="排队等待下载",
            error_code=None,
            error_message=None,
            retryable=0,
            attempts=task.attempts + 1,
            finished_at=None,
            output_path=None,
            output_size=None,
            progress=Progress(),
        )
        self._spawn(task_id, self._run_download(task_id))
        return self.get(task_id)

    async def cancel(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task.status in TERMINAL_STATUSES:
            raise Conflict("任务已经结束，无需取消")

        self._cancel_event(task_id).set()
        self._patch(
            task_id,
            status=TaskStatus.CANCELLED,
            status_reason="已取消",
            finished_at=time.time(),
            retryable=1,
            progress=Progress(),
        )
        self._progress.pop(task_id, None)

        job = self._jobs.get(task_id)
        if task.status is TaskStatus.AWAITING_SELECTION or job is None or job.done():
            self._cleanup_work_dir(task.work_dir)
        else:
            # 下载线程可能正阻塞在网络读上，句柄释放前删不掉：等它结束后再清理。
            # 用独立任务而不是 _spawn，避免覆盖该任务的下载 job 句柄。
            janitor = asyncio.create_task(
                self._cleanup_after_job(task.work_dir, job), name=f"cleanup-{task_id}"
            )
            self._janitor.add(janitor)
            janitor.add_done_callback(self._janitor.discard)
        return self.get(task_id)

    async def _cleanup_after_job(self, work_dir: str | None, job: asyncio.Task) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(job), timeout=180)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception:  # 任务自身异常不影响清理
            pass
        # 回收可能仍持有文件句柄的循环引用（yt-dlp 的对象图经常成环）
        await asyncio.to_thread(gc.collect)
        await asyncio.to_thread(self._cleanup_work_dir, work_dir)

    async def retry(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task.status not in RETRYABLE_STATUSES:
            raise Conflict("当前状态不能重试")
        if task.platform is Platform.YOUTUBE and not self.proxies.has_candidates():
            raise ProxyUnavailable(
                "未配置可用代理：YouTube 只允许通过代理访问，不会回退直连。"
            )
        if task.error_code == "PROXY_UNAVAILABLE":
            self.proxies.invalidate()

        fields: dict[str, Any] = {
            "error_code": None,
            "error_message": None,
            "retryable": 0,
            "finished_at": None,
            "attempts": task.attempts + 1,
            "output_path": None,
            "output_size": None,
            "progress": Progress(),
        }
        if task.selected_option and task.options:
            self._patch(
                task_id,
                status=TaskStatus.DOWNLOAD_QUEUED,
                status_reason="重新排队下载",
                **fields,
            )
            self._spawn(task_id, self._run_download(task_id))
        else:
            self._patch(
                task_id,
                status=TaskStatus.RESOLVE_QUEUED,
                status_reason="重新排队解析",
                **fields,
            )
            self._spawn(task_id, self._run_resolve(task_id))
        return self.get(task_id)

    # -- 快照 --------------------------------------------------------------
    def build_snapshot(self) -> dict[str, Any]:
        tasks = self.store.list_tasks(limit=50)
        visible_ids = {
            task.id
            for task in tasks
            if task.status in ACTIVE_STATUSES or task.status is TaskStatus.AWAITING_SELECTION
        }
        visible = [task for task in tasks if task.id in visible_ids]
        terminal = [task for task in tasks if task.id not in visible_ids][:RECENT_TERMINAL_LIMIT]
        visible.extend(terminal)

        return {
            "type": "snapshot",
            "tasks": [task.to_api(self._queue_info(task)) for task in visible],
            "platforms": {key.value: lane.snapshot() for key, lane in self.lanes.items()},
            "proxy": self._proxy_status,
            "limits": {
                "max_active_tasks": self.settings.max_active_tasks,
                "file_ttl_hours": self.settings.file_ttl_hours,
                "cooldowns": {
                    key.value: lane.cooldown for key, lane in self.lanes.items()
                },
            },
            "server_time": time.time(),
        }

    def _queue_info(self, task: Task) -> dict[str, Any] | None:
        if task.status not in {TaskStatus.RESOLVE_QUEUED, TaskStatus.DOWNLOAD_QUEUED}:
            return None
        return self.lanes[task.platform].describe(task.id)

    # -- 执行 --------------------------------------------------------------
    async def _run_resolve(self, task_id: str) -> None:
        task = self.store.get(task_id)
        if task is None:
            return
        cancel = self._cancel_event(task_id)
        lane = self.lanes[task.platform]
        acquired = False
        try:
            if cancel.is_set():
                raise TaskCancelled()
            proxy = await self.proxies.resolve(task.route)
            await lane.acquire(task_id, cancel)
            acquired = True

            self._patch(
                task_id,
                status=TaskStatus.RESOLVING,
                status_reason="正在获取视频信息",
                started_at=time.time(),
                error_code=None,
                error_message=None,
                retryable=0,
            )
            result = await self.downloader.resolve(task.url, proxy)
            if cancel.is_set():
                raise TaskCancelled()

            self._patch(
                task_id,
                status=TaskStatus.AWAITING_SELECTION,
                status_reason="选择清晰度后开始下载",
                title=result.title,
                duration_s=result.duration_s,
                uploader=result.uploader,
                options=result.options,
                selected_option="best",
                error_code=None,
                error_message=None,
                retryable=0,
            )
        except TaskCancelled as exc:  # noqa: BLE001
            # 清掉 traceback：帧里还引用着 yt-dlp 的文件对象，Windows 上会一直占用分片文件
            exc.__traceback__ = None
            self._mark_cancelled(task_id)
        except AppError as exc:
            self._mark_failed(task_id, exc)
        except Exception as exc:  # 兜底：任何异常都要落到失败状态
            log.exception("解析任务异常：%s", task_id)
            self._mark_failed(
                task_id,
                AppError(f"解析失败：{exc}", code="EXTRACT_FAILED", retryable=True),
            )
        finally:
            if acquired:
                await lane.release()
            if self._cancel.get(task_id) is cancel:
                self._cancel.pop(task_id, None)

    async def _run_download(self, task_id: str) -> None:
        task = self.store.get(task_id)
        if task is None:
            return
        cancel = self._cancel_event(task_id)
        lane = self.lanes[task.platform]
        tracker = ProgressTracker()
        loop = asyncio.get_running_loop()
        acquired = False

        def on_progress(data: dict[str, Any]) -> None:
            # 在 yt-dlp 的线程里调用：只写内存，落盘由 1s 心跳负责
            self._progress[task_id] = tracker.update(data)

        def on_merge(data: dict[str, Any]) -> None:
            if data.get("status") in {"started", "processing"}:
                self._progress[task_id] = tracker.mark_merging()
                loop.call_soon_threadsafe(self._mark_merging, task_id)

        try:
            if cancel.is_set():
                raise TaskCancelled()
            option = task.selected()
            if option is None:
                raise InvalidInput("缺少清晰度选择，请重新解析")
            proxy = await self.proxies.resolve(task.route)
            await lane.acquire(task_id, cancel)
            acquired = True

            self._patch(
                task_id,
                status=TaskStatus.DOWNLOADING,
                status_reason="正在下载",
                started_at=time.time(),
                error_code=None,
                error_message=None,
                retryable=0,
            )
            result = await self.downloader.download(
                url=task.url,
                selector=option.selector,
                work_dir=Path(task.work_dir or self.settings.work_dir / task_id),
                proxy=proxy,
                cancel=cancel,
                on_progress=on_progress,
                on_merge=on_merge,
            )
            if cancel.is_set():
                raise TaskCancelled()

            self._patch(
                task_id,
                status=TaskStatus.COMPLETED,
                status_reason="下载完成",
                output_path=str(result.output_path),
                output_size=result.size,
                duration_s=result.duration_s or task.duration_s,
                progress=self._progress.get(task_id)
                or Progress(phase="done", percent=100.0, updated_at=time.time()),
                finished_at=time.time(),
                error_code=None,
                error_message=None,
                retryable=0,
            )
            self._cleanup_temp(task.work_dir, keep=result.output_path)
            self._progress.pop(task_id, None)
        except TaskCancelled as exc:  # noqa: BLE001
            # 清掉 traceback：帧里还引用着 yt-dlp 的文件对象，Windows 上会一直占用分片文件
            exc.__traceback__ = None
            self._mark_cancelled(task_id)
        except AppError as exc:
            self._mark_failed(task_id, exc)
        except Exception as exc:
            log.exception("下载任务异常：%s", task_id)
            self._mark_failed(
                task_id,
                AppError(f"下载失败：{exc}", code="DOWNLOAD_FAILED", retryable=True),
            )
        finally:
            if acquired:
                await lane.release()
            if self._cancel.get(task_id) is cancel:
                self._cancel.pop(task_id, None)

    # -- 状态写入 ----------------------------------------------------------
    def _mark_merging(self, task_id: str) -> None:
        task = self.store.get(task_id)
        if task is not None and task.status is TaskStatus.DOWNLOADING:
            self._patch(
                task_id,
                status=TaskStatus.MERGING,
                status_reason="音视频下载完成，正在无损合并",
            )

    def _mark_cancelled(self, task_id: str) -> None:
        task = self.store.get(task_id)
        if task is None:
            return
        if task.status not in TERMINAL_STATUSES:
            self._patch(
                task_id,
                status=TaskStatus.CANCELLED,
                status_reason="已取消",
                finished_at=time.time(),
                retryable=1,
                progress=Progress(),
            )
        self._progress.pop(task_id, None)
        self._cleanup_work_dir(task.work_dir)

    def _mark_failed(self, task_id: str, error: AppError) -> None:
        task = self.store.get(task_id)
        if task is None:
            return
        if task.status is TaskStatus.CANCELLED:
            return
        self._patch(
            task_id,
            status=TaskStatus.FAILED,
            status_reason=error.message,
            error_code=error.code,
            error_message=error.message,
            retryable=1 if error.retryable else 0,
            finished_at=time.time(),
            progress=Progress(),
        )
        self._progress.pop(task_id, None)
        # 失败任务的残留分片立即清理（只有「服务重启中断」才保留分片用于续传）
        self._cleanup_work_dir(task.work_dir)

    def _patch(self, task_id: str, **fields: Any) -> None:
        try:
            self.store.update(task_id, **fields)
        except Exception:  # 状态写失败不能拖垮任务
            log.exception("写入任务状态失败：%s", task_id)

    # -- 心跳 --------------------------------------------------------------
    async def _tick(self) -> None:
        ticks = 0
        while True:
            await asyncio.sleep(1)
            try:
                await asyncio.to_thread(self._persist_progress)
                if ticks % 30 == 0:
                    self._proxy_status = await self.proxies.status()
                self.hub.publish(self.build_snapshot())
                if ticks % 900 == 0:
                    await asyncio.to_thread(self._cleanup_expired)
                ticks += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("后台心跳异常")

    def _persist_progress(self) -> None:
        for task_id, progress in list(self._progress.items()):
            if progress.updated_at <= self._persisted.get(task_id, 0.0):
                continue
            self._patch(task_id, progress=progress)
            self._persisted[task_id] = progress.updated_at

    # -- 清理 --------------------------------------------------------------
    def _cleanup_work_dir(self, work_dir: str | None) -> None:
        if not work_dir:
            return
        base = self.settings.work_dir.resolve()
        try:
            target = Path(work_dir).resolve()
        except OSError:
            return
        # 只允许删除数据目录下的任务目录
        if target == base or base not in target.parents:
            return
        # Windows 上 yt-dlp 的工作线程可能还没释放 .part 句柄，删除会静默失败，重试几次
        for _ in range(6):
            shutil.rmtree(target, ignore_errors=True)
            if not target.exists():
                return
            time.sleep(0.25)
        log.warning("清理任务目录失败（文件可能仍被占用）：%s", target)

    def _cleanup_temp(self, work_dir: str | None, keep: Path | None) -> None:
        if not work_dir:
            return
        directory = Path(work_dir)
        if not directory.exists():
            return
        for item in directory.iterdir():
            if (
                item.is_file()
                and item != keep
                and item.name.endswith(TEMP_SUFFIXES)
            ):
                with contextlib.suppress(OSError):
                    item.unlink()

    def _cleanup_expired(self) -> None:
        now = time.time()
        cutoff = now - self.settings.file_ttl_hours * 3600
        for task in self.store.terminal_before(cutoff, limit=100):
            self._cleanup_work_dir(task.work_dir)
            self.store.delete(task.id)

        work_root = self.settings.work_dir
        if not work_root.exists():
            return
        known = {task.work_dir for task in self.store.list_tasks(limit=2000)}
        for child in work_root.iterdir():
            if not child.is_dir() or str(child) in known:
                continue
            with contextlib.suppress(OSError):
                if now - child.stat().st_mtime > 86400:
                    shutil.rmtree(child, ignore_errors=True)

    # -- 内部工具 ----------------------------------------------------------
    def _cancel_event(self, task_id: str) -> asyncio.Event:
        event = self._cancel.get(task_id)
        if event is None:
            event = asyncio.Event()
            self._cancel[task_id] = event
        return event

    def _spawn(self, task_id: str, coro: Any) -> None:
        previous = self._jobs.pop(task_id, None)
        if previous is not None and not previous.done():
            previous.cancel()
        job = asyncio.create_task(coro, name=f"task-{task_id}")
        self._jobs[task_id] = job
        job.add_done_callback(lambda finished: self._forget(task_id, finished))

    def _forget(self, task_id: str, job: asyncio.Task[None]) -> None:
        if self._jobs.get(task_id) is job:
            self._jobs.pop(task_id, None)
        if job.cancelled():
            return
        error = job.exception()
        if error is not None:
            log.error("任务 %s 未捕获异常", task_id, exc_info=error)
