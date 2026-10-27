"""代理选择：本地客户端代理优先，服务器端代理兜底；代理不可用即失败。

国内平台（route=direct）永远返回 None，不会因为配置了代理而走代理；
YouTube（route=proxy）永远返回代理，绝不回退直连。
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

from .config import Settings
from .errors import ProxyUnavailable
from .models import Route

SUPPORTED_SCHEMES = {"http", "https", "socks5", "socks5h", "socks4"}


@dataclass(frozen=True)
class ProxyCandidate:
    name: str
    url: str


def normalize_proxy(raw: str | None) -> str | None:
    """把 127.0.0.1:7890 之类的输入补全为可用的代理 URL。"""
    value = (raw or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() not in SUPPORTED_SCHEMES:
        return None
    if not parts.hostname:
        return None
    return value.rstrip("/")


def mask_proxy(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    auth = "***@" if parts.username else ""
    return f"{parts.scheme}://{auth}{host}{port}"


def read_system_proxy() -> str | None:
    """读取 Windows 系统代理（Clash/v2ray 等客户端默认会写入这里）。"""
    if os.name != "nt":
        return None
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            try:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            except FileNotFoundError:
                return None
            if not enabled:
                return None
            try:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            except FileNotFoundError:
                return None
    except OSError:
        return None

    if not server:
        return None
    if "=" in server:
        mapping = dict(
            chunk.split("=", 1) for chunk in server.split(";") if "=" in chunk
        )
        server = (
            mapping.get("https")
            or mapping.get("http")
            or next(iter(mapping.values()), "")
        )
    return normalize_proxy(server)


def _tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class ProxyManager:
    def __init__(
        self,
        settings: Settings,
        prober: Callable[[str], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.mode = settings.proxy_mode
        self._probe = prober or self._probe_blocking
        self._health: dict[str, tuple[float, bool]] = {}
        self._selected: str | None = None

    # -- 候选 --------------------------------------------------------------
    def candidates(self) -> list[ProxyCandidate]:
        if self.mode == "off":
            return []

        items: list[ProxyCandidate] = []
        local = normalize_proxy(self.settings.proxy_local)
        if local:
            items.append(ProxyCandidate("local", local))
        system = read_system_proxy()
        if system and system not in {item.url for item in items}:
            items.append(ProxyCandidate("system", system))
        server = normalize_proxy(self.settings.proxy_server)
        if server and server not in {item.url for item in items}:
            items.append(ProxyCandidate("server", server))

        if self.mode == "local":
            items = [item for item in items if item.name in {"local", "system"}]
        elif self.mode == "server":
            items = [item for item in items if item.name == "server"]
        return items

    def has_candidates(self) -> bool:
        return bool(self.candidates())

    # -- 健康检查 ----------------------------------------------------------
    async def healthy(self, url: str) -> bool:
        cached = self._health.get(url)
        if cached:
            checked_at, ok = cached
            ttl = self.settings.proxy_ttl_s if ok else self.settings.proxy_failure_ttl_s
            if time.monotonic() - checked_at < ttl:
                return ok
        ok = await asyncio.to_thread(self._probe, url)
        self._health[url] = (time.monotonic(), ok)
        return ok

    async def resolve(self, route: Route) -> str | None:
        if route is Route.DIRECT:
            return None

        candidates = self.candidates()
        if not candidates:
            raise ProxyUnavailable(
                "未配置可用代理：YouTube 只允许通过代理访问，不会回退直连。"
                "请在设置里配置本地代理或服务器代理。"
            )

        for candidate in candidates:
            if await self.healthy(candidate.url):
                self._selected = candidate.url
                return candidate.url

        tried = "、".join(f"{item.name} {mask_proxy(item.url)}" for item in candidates)
        raise ProxyUnavailable(
            f"代理不可用（已尝试：{tried}），任务已停止，未回退直连。请检查代理后重试。"
        )

    async def status(self) -> dict[str, Any]:
        items = []
        first_healthy: str | None = None
        for candidate in self.candidates():
            healthy = await self.healthy(candidate.url)
            if healthy and first_healthy is None:
                first_healthy = candidate.url
            items.append(
                {
                    "name": candidate.name,
                    "url": mask_proxy(candidate.url),
                    "healthy": healthy,
                }
            )
        if first_healthy:
            # 页面顶部的「代理可用」提示与真实路由选择保持一致
            self._selected = first_healthy
        return {
            "mode": self.mode,
            "probe_url": self.settings.proxy_probe_url,
            "candidates": items,
            "selected": mask_proxy(self._selected),
            "available": first_healthy is not None,
        }

    def invalidate(self) -> None:
        self._health.clear()
        self._selected = None

    # -- 实际探测 ----------------------------------------------------------
    def _probe_blocking(self, proxy_url: str) -> bool:
        parts = urlsplit(proxy_url)
        host = parts.hostname or ""
        # socks 需要 PySocks，未安装时只验证端口连通性
        if parts.scheme.lower().startswith("socks"):
            return _tcp_reachable(host, parts.port or 1080)
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not host:
                return False

        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
        request = urllib.request.Request(
            self.settings.proxy_probe_url,
            method="HEAD",
            headers={"User-Agent": self.settings.user_agent},
        )
        try:
            with opener.open(request, timeout=self.settings.proxy_probe_timeout) as response:
                return int(response.status) < 500
        except urllib.error.HTTPError as exc:
            return int(exc.code) < 500
        except Exception:
            return False
