"""链接提取与平台识别：真实分享文案样式。"""

from __future__ import annotations

import pytest

from app.errors import InvalidInput, UnsupportedPlatform
from app.models import Platform
from app.security import validate_task_input


def test_bilibili_plain_link_keeps_part_param():
    url, platform = validate_task_input(
        "https://www.bilibili.com/video/BV1GJ411x7h7?spm_id_from=333.999&p=2"
    )
    assert platform is Platform.BILIBILI
    assert url == "https://www.bilibili.com/video/BV1GJ411x7h7?p=2"


def test_b23_short_link():
    url, platform = validate_task_input("https://b23.tv/AbCdEf1")
    assert platform is Platform.BILIBILI
    assert url == "https://b23.tv/AbCdEf1"


def test_douyin_share_text():
    text = (
        "7.43 复制打开抖音，看看【城市夜景】的作品  https://v.douyin.com/iRNBho6u/ "
        "复制此链接，打开Dou音搜索，直接观看视频！"
    )
    url, platform = validate_task_input(text)
    assert platform is Platform.DOUYIN
    assert url == "https://v.douyin.com/iRNBho6u/"


def test_douyin_full_link_with_tracking():
    url, platform = validate_task_input(
        "https://www.douyin.com/video/7123456789012345678?previous_page=app_code_link"
    )
    assert platform is Platform.DOUYIN
    assert url == "https://www.douyin.com/video/7123456789012345678"


def test_youtube_short_link():
    url, platform = validate_task_input("https://youtu.be/dQw4w9WgXcQ?si=tracking")
    assert platform is Platform.YOUTUBE
    assert url == "https://youtu.be/dQw4w9WgXcQ"


def test_youtube_watch_link_follows_share_text():
    url, platform = validate_task_input(
        "听听这个 https://www.youtube.com/watch?v=dQw4w9WgXcQ&utm_source=share 很好听"
    )
    assert platform is Platform.YOUTUBE
    assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_bare_host_without_scheme():
    url, platform = validate_task_input("b23.tv/AbCdEf1")
    assert platform is Platform.BILIBILI
    assert url == "https://b23.tv/AbCdEf1"


def test_reject_unsupported_platform():
    with pytest.raises(UnsupportedPlatform) as excinfo:
        validate_task_input("https://vimeo.com/123456")
    assert "暂不支持" in excinfo.value.message


def test_reject_private_host_and_ip_literal():
    # 非白名单主机一律拒绝，不发起任何网络请求（防 SSRF）
    for text in ("http://127.0.0.1:8080/video", "http://localhost/video", "file:///etc/passwd"):
        with pytest.raises((UnsupportedPlatform, InvalidInput)):
            validate_task_input(text)


def test_reject_non_http_scheme():
    with pytest.raises(InvalidInput):
        validate_task_input("ftp://www.bilibili.com/video/BV1GJ411x7h7")


def test_reject_text_without_link():
    with pytest.raises(InvalidInput) as excinfo:
        validate_task_input("这个视频真好看，但是没有链接")
    assert "没有识别到链接" in excinfo.value.message


def test_reject_overlong_input():
    with pytest.raises(InvalidInput):
        validate_task_input("https://b23.tv/AbCdEf1 " + "x" * 3000)
