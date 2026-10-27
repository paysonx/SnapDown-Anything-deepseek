"""yt-dlp 封装：解析元信息、构建清晰度、下载、进度回调、成品校验。

所有阻塞调用都在线程里执行（由上层用 asyncio.to_thread 包住），
进度钩子直接回传原始事件，由 ProgressTracker 聚合成总体进度。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .config import Settings
from .errors import DownloadFailed, ExtractionFailed, TaskCancelled
from .models import QualityOption
from .progress import ProgressTracker

log = logging.getLogger(__name__)

TEMP_SUFFIXES = (".part", ".ytdl", ".temp", ".part-Frag")


@dataclass
class ResolveResult:
    title: str
    duration_s: float | None
    uploader: str | None
    options: list[QualityOption]


@dataclass
class DownloadResult:
    output_path: Path
    size: int
    duration_s: float | None


class _YdlLogger:
    """把 yt-dlp 的日志接到标准 logging，避免污染 stdout。"""

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug]"):
            log.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        log.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.error("yt-dlp: %s", msg)


def _filesize(fmt: dict[str, Any]) -> int | None:
    value = fmt.get("filesize") or fmt.get("filesize_approx")
    return int(value) if value else None


def _pick_audio(formats: list[dict[str, Any]]) -> dict[str, Any] | None:
    audios = [
        fmt
        for fmt in formats
        if (fmt.get("acodec") or "none") != "none"
        and (fmt.get("vcodec") or "none") == "none"
    ]
    if not audios:
        return None
    return max(audios, key=lambda fmt: (float(fmt.get("abr") or 0), _filesize(fmt) or 0))


def build_quality_options(info: dict[str, Any]) -> list[QualityOption]:
    """把 yt-dlp 的 formats 折叠成「每档分辨率一个选项」。

    默认第一项为最佳可用画质（bestvideo*+bestaudio/best）；
    其余按高度降序，只保留画面最好的那一档，避免同分辨率刷屏。
    """
    all_formats = info.get("formats") or []
    formats = [fmt for fmt in all_formats if (fmt.get("vcodec") or "none") != "none"]
    if not formats:
        raise ExtractionFailed("没有找到可下载的视频流（可能是会员、DRM 或地区限制内容）")

    audio = _pick_audio(all_formats)
    best_by_height: dict[int, tuple[tuple[float, float, float], dict[str, Any]]] = {}
    for fmt in formats:
        height = int(fmt.get("height") or 0)
        score = (
            float(fmt.get("fps") or 0),
            float(fmt.get("tbr") or 0),
            float(_filesize(fmt) or 0),
        )
        current = best_by_height.get(height)
        if current is None or score > current[0]:
            best_by_height[height] = (score, fmt)

    options: list[QualityOption] = [
        QualityOption(
            id="best",
            label="最佳可用画质",
            detail="自动选择最高分辨率与最佳音轨",
            selector="bestvideo*+bestaudio/best",
            is_best=True,
        )
    ]

    for height, (_, fmt) in sorted(best_by_height.items(), key=lambda kv: kv[0], reverse=True)[:5]:
        format_id = str(fmt.get("format_id"))
        has_audio = (fmt.get("acodec") or "none") != "none"
        selector = format_id if has_audio else f"{format_id}+bestaudio/best"
        size = _filesize(fmt)
        if not has_audio and audio:
            audio_size = _filesize(audio)
            if size and audio_size:
                size += audio_size
            else:
                size = None

        detail_parts = [(fmt.get("ext") or "mp4").upper()]
        if fmt.get("fps"):
            detail_parts.append(f"{int(float(fmt['fps']))}fps")
        vcodec = (fmt.get("vcodec") or "").split(".")[0]
        if vcodec and vcodec != "none":
            detail_parts.append(vcodec.upper())
        detail_parts.append("单文件" if has_audio else "音视频合并")

        options.append(
            QualityOption(
                id=f"fmt-{format_id}",
                label=f"{height}P" if height else "原始画质",
                detail=" · ".join(detail_parts),
                selector=selector,
                height=height or None,
                ext=fmt.get("ext"),
                fps=float(fmt["fps"]) if fmt.get("fps") else None,
                size_bytes=size,
            )
        )
    return options


class YtDlpDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ffmpeg = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg"
        self.ffprobe = settings.ffprobe_path or shutil.which("ffprobe") or "ffprobe"

    # -- 选项 --------------------------------------------------------------
    def _base_opts(self, proxy: str | None) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "noplaylist": True,
            "no_color": True,
            "ignoreerrors": False,
            "socket_timeout": 10,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 2,
            "cachedir": str(self.settings.data_dir / "yt-dlp-cache"),
            "http_headers": {"User-Agent": self.settings.user_agent},
            "logger": _YdlLogger(),
            # 空字符串 = 显式禁用代理。国内平台即使客户端开着系统代理也必须直连，
            # 不能让 urllib 读到系统代理设置后偷偷走代理。
            "proxy": proxy or "",
        }
        if self.ffmpeg and Path(self.ffmpeg).exists():
            opts["ffmpeg_location"] = str(Path(self.ffmpeg).parent)
        return opts

    # -- 解析 --------------------------------------------------------------
    async def resolve(self, url: str, proxy: str | None) -> ResolveResult:
        return await asyncio.to_thread(self._resolve_sync, url, proxy)

    def _resolve_sync(self, url: str, proxy: str | None) -> ResolveResult:
        opts = self._base_opts(proxy)
        opts.update({"skip_download": True, "extract_flat": False})
        with YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except DownloadError as exc:
                raise ExtractionFailed(_clean_error(exc)) from exc
        info = _first_entry(info)
        if not info:
            raise ExtractionFailed("解析失败：没有获取到视频信息")
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            raise ExtractionFailed("直播暂不支持")

        options = build_quality_options(info)
        duration = info.get("duration")
        return ResolveResult(
            title=(info.get("title") or "未命名视频").strip()[:200],
            duration_s=float(duration) if duration else None,
            uploader=(info.get("uploader") or None),
            options=options,
        )

    # -- 下载 --------------------------------------------------------------
    async def download(
        self,
        *,
        url: str,
        selector: str,
        work_dir: Path,
        proxy: str | None,
        cancel: Any,
        on_progress: Callable[[dict[str, Any]], None],
        on_merge: Callable[[dict[str, Any]], None],
    ) -> DownloadResult:
        return await asyncio.to_thread(
            self._download_sync,
            url,
            selector,
            work_dir,
            proxy,
            cancel,
            on_progress,
            on_merge,
        )

    def _download_sync(
        self,
        url: str,
        selector: str,
        work_dir: Path,
        proxy: str | None,
        cancel: Any,
        on_progress: Callable[[dict[str, Any]], None],
        on_merge: Callable[[dict[str, Any]], None],
    ) -> DownloadResult:
        work_dir.mkdir(parents=True, exist_ok=True)
        opts = self._base_opts(proxy)
        opts.update(
            {
                "format": selector,
                "outtmpl": "video.%(ext)s",
                "paths": {"home": str(work_dir), "temp": str(work_dir)},
                "continuedl": True,
                "overwrites": False,
                "nopart": False,
                "concurrent_fragment_downloads": 1,
            }
        )
        opts["progress_hooks"] = [_checked(cancel, on_progress)]
        opts["postprocessor_hooks"] = [_checked(cancel, on_merge)]

        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except TaskCancelled:
            raise
        except DownloadError as exc:
            raise DownloadFailed(_clean_error(exc)) from exc

        info = _first_entry(info) or {}
        output = self._find_output(work_dir)
        if output is None:
            raise DownloadFailed("下载结束但没有找到输出文件")
        self._verify(output, info.get("duration"))
        return DownloadResult(
            output_path=output,
            size=output.stat().st_size,
            duration_s=float(info["duration"]) if info.get("duration") else None,
        )

    # -- 成品校验 ----------------------------------------------------------
    def _find_output(self, work_dir: Path) -> Path | None:
        candidates = [
            item
            for item in work_dir.iterdir()
            if item.is_file() and not item.name.endswith(TEMP_SUFFIXES)
        ]
        preferred = [item for item in candidates if item.stem.startswith("video")]
        pool = preferred or candidates
        if not pool:
            return None
        return max(pool, key=lambda item: item.stat().st_mtime)

    def _verify(self, path: Path, expected_duration: float | None) -> None:
        if not path.exists():
            raise DownloadFailed("合并后未找到输出文件")
        if path.stat().st_size <= 0:
            raise DownloadFailed("输出文件大小为 0，合并可能失败")

        probe = self.ffprobe_info(path)
        if probe is None:
            log.warning("ffprobe 不可用，仅做文件大小校验：%s", path)
            return
        duration = probe.get("duration")
        if not duration:
            raise DownloadFailed("文件校验失败：无法读取媒体时长，成品可能损坏")
        if expected_duration and abs(duration - expected_duration) > max(2.0, expected_duration * 0.02):
            raise DownloadFailed(
                f"文件校验失败：成品时长 {duration:.0f}s 与源时长 {expected_duration:.0f}s 不一致"
            )

    def ffprobe_info(self, path: Path) -> dict[str, Any] | None:
        cmd = [
            self.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ]
        try:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("ffprobe 调用失败：%s", exc)
            return None
        if completed.returncode != 0:
            raise DownloadFailed(f"文件校验失败：{completed.stderr.strip()[:200]}")
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return None
        fmt = payload.get("format") or {}
        return {
            "duration": float(fmt["duration"]) if fmt.get("duration") else None,
            "size": int(fmt.get("size") or 0),
        }

    def tools_status(self) -> dict[str, Any]:
        def version(binary: str) -> str | None:
            try:
                out = subprocess.run(
                    [binary, "-version"], capture_output=True, text=True, timeout=10, check=False
                )
            except (OSError, subprocess.SubprocessError):
                return None
            if out.returncode != 0:
                return None
            return (out.stdout or "").splitlines()[0][:120]

        return {"ffmpeg": version(self.ffmpeg), "ffprobe": version(self.ffprobe)}


def _checked(cancel: Any, callback: Callable[[dict[str, Any]], None]):
    def hook(data: dict[str, Any]) -> None:
        if cancel.is_set():
            raise TaskCancelled()
        try:
            callback(data)
        except Exception:  # 回调异常不能打断下载
            log.exception("进度回调失败")

    return hook


def _first_entry(info: dict[str, Any] | None) -> dict[str, Any] | None:
    if not info:
        return None
    if info.get("_type") in {"playlist", "multi_video"}:
        entries = [entry for entry in (info.get("entries") or []) if entry]
        return entries[0] if entries else None
    return info


def _clean_error(exc: Exception) -> str:
    text = str(exc).replace("ERROR: ", "").strip()
    lines = [line for line in text.splitlines() if line.strip()]
    message = lines[-1] if lines else "未知错误"
    if "Sign in to confirm" in message or "cookies" in message.lower():
        return "该视频需要登录或 Cookies，当前版本不支持（未包含 Cookies 上传）"
    if "Unsupported URL" in message:
        return "暂不支持该链接类型"
    if "Video unavailable" in message or "not available" in message.lower():
        return "视频不可用（可能已删除、地区限制或需要登录）"
    # 平台 CDN 临时限流/拒绝：如实说明，允许用户稍后重试
    if any(code in message for code in ("503", "429", "Too Many Requests")):
        return f"平台临时限流（{message[:60]}），请稍后重试"
    return message[:300]
