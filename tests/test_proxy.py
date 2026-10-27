"""代理选择：本地客户端代理优先、服务器代理兜底、绝不回退直连。"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.config import Settings
from app.errors import ProxyUnavailable
from app.models import Route
from app.proxy import ProxyManager

LOCAL = "http://127.0.0.1:10808"
SERVER = "http://proxy.example.com:3128"


def _manager(settings: Settings, *, healthy: set[str] | None = None) -> ProxyManager:
    healthy = healthy or set()

    def prober(url: str) -> bool:
        return url in healthy

    return ProxyManager(settings, prober=prober)


def test_direct_route_never_uses_proxy(settings):
    manager = _manager(replace(settings, proxy_mode="auto"))
    assert asyncio.run(manager.resolve(Route.DIRECT)) is None


def test_local_proxy_preferred_over_server(settings):
    settings = replace(settings, proxy_mode="auto", proxy_local=LOCAL, proxy_server=SERVER)
    manager = _manager(settings, healthy={LOCAL, SERVER})
    assert asyncio.run(manager.resolve(Route.PROXY)) == LOCAL


def test_server_proxy_is_fallback(settings):
    settings = replace(settings, proxy_mode="auto", proxy_local=LOCAL, proxy_server=SERVER)
    manager = _manager(settings, healthy={SERVER})
    assert asyncio.run(manager.resolve(Route.PROXY)) == SERVER


def test_no_proxy_fallback_to_direct(settings):
    settings = replace(settings, proxy_mode="auto", proxy_local=LOCAL, proxy_server=SERVER)
    manager = _manager(settings, healthy=set())
    with pytest.raises(ProxyUnavailable) as excinfo:
        asyncio.run(manager.resolve(Route.PROXY))
    assert "未回退直连" in excinfo.value.message


def test_unconfigured_proxy_is_rejected(settings):
    settings = replace(settings, proxy_mode="off", proxy_local="", proxy_server="")
    manager = _manager(settings)
    assert manager.has_candidates() is False
    with pytest.raises(ProxyUnavailable):
        asyncio.run(manager.resolve(Route.PROXY))


def test_status_masks_credentials(settings):
    settings = replace(
        settings,
        proxy_mode="local",
        proxy_local="http://demo-user:demo-pass@127.0.0.1:10808",
        proxy_server="",
    )
    manager = _manager(settings, healthy={"http://demo-user:demo-pass@127.0.0.1:10808"})
    status = asyncio.run(manager.status())
    assert status["available"] is True
    assert "demo-pass" not in str(status)
    assert "***" in status["candidates"][0]["url"]
