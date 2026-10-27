"""安全校验：输入边界、SSRF 白名单、路径穿越。"""

from __future__ import annotations

from pathlib import Path

from .errors import InvalidInput, UnsupportedPlatform
from .models import Platform
from .platforms import PLATFORM_HOSTS, detect_platform, extract_url, normalize_url


def validate_task_input(text: str, *, max_chars: int = 2000) -> tuple[str, Platform]:
    """把用户输入（链接或分享文案）变成（规范化 URL, 平台）。

    只放行白名单平台的 http/https 链接：
    - 拒绝其它协议（file://、ftp:// 等），避免任意网络/本地读取；
    - 拒绝非白名单域名，避免 SSRF 与任意站点抓取。
    """
    if not text or not text.strip():
        raise InvalidInput("请粘贴视频链接或分享文案")
    if len(text) > max_chars:
        raise InvalidInput(f"输入过长，最多 {max_chars} 个字符")

    url = normalize_url(extract_url(text))
    host = (url.split("/", 3)[2] if "://" in url else "").split(":")[0].lower()
    platform = detect_platform(host)
    if platform is None:
        supported = "、".join(
            host for hosts in PLATFORM_HOSTS.values() for host in hosts[:1]
        )
        raise UnsupportedPlatform(f"暂不支持该平台，当前仅支持 {supported}")
    return url, platform


def ensure_inside(base: Path, target: Path) -> Path:
    """确认 target 位于 base 之内，阻止路径穿越访问任意文件。"""
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if target_resolved != base_resolved and base_resolved not in target_resolved.parents:
        raise InvalidInput("非法文件路径")
    return target_resolved
