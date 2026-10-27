"""清晰度候选：每档分辨率一个选项，默认最佳可用画质。"""

from __future__ import annotations

import pytest

from app.errors import ExtractionFailed
from app.ytdlp_runner import build_quality_options
from tests.conftest import FAKE_FORMATS


def _options():
    return build_quality_options({"formats": FAKE_FORMATS})


def test_best_is_default_first_option():
    options = _options()
    assert options[0].id == "best"
    assert options[0].is_best is True
    assert options[0].label == "最佳可用画质"
    assert options[0].selector == "bestvideo*+bestaudio/best"


def test_heights_are_deduped_and_sorted_desc():
    options = _options()
    heights = [option.height for option in options if option.height]
    assert heights == [1080, 360]


def test_video_only_stream_merges_best_audio():
    option = next(item for item in _options() if item.height == 1080)
    assert option.selector == "137+bestaudio/best"
    # 1080P 视频 800 字节 + 最佳音轨 200 字节
    assert option.size_bytes == 1000
    assert "音视频合并" in option.detail


def test_muxed_stream_keeps_single_file():
    option = next(item for item in _options() if item.height == 360)
    assert option.selector == "18"
    assert option.size_bytes == 300
    assert "单文件" in option.detail


def test_no_video_stream_fails_fast():
    with pytest.raises(ExtractionFailed):
        build_quality_options({"formats": []})
