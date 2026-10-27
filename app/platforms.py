"""平台识别与链接提取：只接受白名单内的平台域名。"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import InvalidInput, UnsupportedPlatform
from .models import Platform

PLATFORM_HOSTS: dict[Platform, tuple[str, ...]] = {
    Platform.BILIBILI: ("bilibili.com", "b23.tv"),
    Platform.DOUYIN: ("douyin.com", "iesdouyin.com"),
    Platform.YOUTUBE: ("youtube.com", "youtu.be"),
}

# 分享链接里与视频定位无关的追踪参数，解析前剔除，避免任务判重失效
TRACKING_PARAMS = {
    "spm_id_from",
    "vd_source",
    "from_source",
    "from_spmid",
    "share_source",
    "share_medium",
    "share_plat",
    "share_tag",
    "share_session_id",
    "share_id",
    "share_from",
    "unique_k",
    "bbid",
    "ts",
    "msource",
    "si",
    "feature",
    "kw",
    "timestamp",
    "previous_page",
    "previous_loc",
    "enter_from",
    "app",
    "source",
}

_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BARE_PATTERN = re.compile(
    r"(?<![\w.-])("
    + "|".join(
        re.escape(host) for hosts in PLATFORM_HOSTS.values() for host in hosts
    )
    + r")/[^\s<>\"']*",
    re.IGNORECASE,
)
_TRAILING = "，。！？；：、）】》」』\"'<>."


def extract_url(text: str) -> str:
    """从纯链接或分享文案中提取第一个受支持的链接。"""
    url = None
    match = _URL_PATTERN.search(text)
    if match:
        url = match.group(0)
    else:
        bare = _BARE_PATTERN.search(text)
        if bare:
            url = "https://" + bare.group(0)

    if not url:
        raise InvalidInput("没有识别到链接，请粘贴视频链接或完整分享文案")

    url = url.rstrip(_TRAILING)
    if not _URL_PATTERN.fullmatch(url):
        url = "https://" + url
    return url


def normalize_url(url: str) -> str:
    """规范化 URL：补协议、转小写域名、去掉追踪参数与 fragment。"""
    raw = url.strip()
    parts = urlsplit(raw)
    if not parts.scheme:
        raw = "https://" + raw
        parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"}:
        raise InvalidInput("仅支持 http/https 链接")

    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise InvalidInput("链接缺少有效域名")
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidInput("链接端口不合法") from exc

    netloc = host if port is None else f"{host}:{port}"
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")
    ]
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def detect_platform(host: str) -> Platform | None:
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return None
    for platform, suffixes in PLATFORM_HOSTS.items():
        for suffix in suffixes:
            if host == suffix or host.endswith("." + suffix):
                return platform
    return None


def platform_of_url(url: str) -> Platform:
    platform = detect_platform(urlsplit(url).hostname or "")
    if platform is None:
        raise UnsupportedPlatform("暂不支持该平台，当前仅支持 B站、抖音、YouTube")
    return platform
