"""多流进度聚合。

yt-dlp 对「视频流 + 音频流」分别回调进度钩子，这里把两条流合并成
一个总体进度；任一流大小未知时 overall 百分比保持 None（禁止编造）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .models import Progress

STREAM_LABELS = {"video": "视频流", "audio": "音频流", "single": "媒体文件"}
STREAM_ORDER = {"video": 0, "single": 1, "audio": 2}


def stream_kind(info: dict[str, Any]) -> str:
    has_video = (info.get("vcodec") or "none") != "none"
    has_audio = (info.get("acodec") or "none") != "none"
    if has_video and has_audio:
        return "single"
    if has_audio:
        return "audio"
    return "video"


@dataclass
class _Stream:
    key: str
    kind: str
    downloaded: int = 0
    total: int | None = None
    estimated: bool = False
    done: bool = False


@dataclass
class ProgressTracker:
    _streams: dict[str, _Stream] = field(default_factory=dict)
    _phase: str | None = None
    _merging: bool = False
    _speed: float | None = None
    _eta: int | None = None

    def _stream(self, info: dict[str, Any]) -> _Stream:
        key = str(info.get("format_id") or info.get("format") or "unknown")
        stream = self._streams.get(key)
        if stream is None:
            stream = _Stream(key=key, kind=stream_kind(info))
            self._streams[key] = stream
        return stream

    def update(self, hook_data: dict[str, Any]) -> Progress:
        info = hook_data.get("info_dict") or {}
        stream = self._stream(info)
        status = hook_data.get("status")

        if status == "downloading":
            downloaded = int(hook_data.get("downloaded_bytes") or 0)
            stream.downloaded = max(stream.downloaded, downloaded)
            total = hook_data.get("total_bytes") or hook_data.get("total_bytes_estimate")
            if total:
                stream.total = int(total)
                stream.estimated = hook_data.get("total_bytes") is None
            self._phase = stream.kind
            speed = hook_data.get("speed")
            self._speed = float(speed) if speed else None
            eta = hook_data.get("eta")
            self._eta = int(eta) if eta is not None else None
        elif status == "finished":
            stream.done = True
            total = hook_data.get("total_bytes") or hook_data.get("total_bytes_estimate")
            if total:
                stream.total = int(total)
            if stream.total:
                stream.downloaded = stream.total
            else:
                stream.downloaded = max(
                    stream.downloaded, int(hook_data.get("downloaded_bytes") or 0)
                )

        return self.snapshot()

    def mark_merging(self) -> Progress:
        self._merging = True
        self._phase = "merging"
        self._speed = None
        self._eta = None
        return self.snapshot()

    def snapshot(self) -> Progress:
        streams = sorted(self._streams.values(), key=lambda s: STREAM_ORDER.get(s.kind, 9))
        downloaded = sum(item.downloaded for item in streams)
        totals_known = bool(streams) and all(item.total for item in streams)
        total = sum(int(item.total) for item in streams) if totals_known else None
        percent = None
        if total and total > 0:
            percent = min(100.0, round(downloaded / total * 100, 1))

        phase = self._phase
        if self._merging:
            phase = "merging"
        elif phase is None and streams and not self._streams_active():
            phase = streams[0].kind

        return Progress(
            phase=phase,
            downloaded_bytes=downloaded,
            total_bytes=total,
            total_estimated=any(item.estimated for item in streams),
            percent=percent,
            speed_bps=None if self._merging else self._speed,
            eta_s=None if self._merging else self._eta,
            streams=[
                {
                    "kind": item.kind,
                    "label": STREAM_LABELS.get(item.kind, item.kind),
                    "downloaded_bytes": item.downloaded,
                    "total_bytes": item.total,
                    "percent": (
                        min(100.0, round(item.downloaded / item.total * 100, 1))
                        if item.total
                        else None
                    ),
                    "done": item.done,
                }
                for item in streams
            ],
            updated_at=time.time(),
        )

    def _streams_active(self) -> bool:
        return any(not item.done for item in self._streams.values())
