"""路径安全：文件只能落在任务目录内。"""

from __future__ import annotations

import pytest

from app.errors import InvalidInput
from app.security import ensure_inside


def test_inside_path_is_allowed(tmp_path):
    base = tmp_path / "work"
    base.mkdir()
    target = base / "video.mp4"
    target.write_bytes(b"data")
    assert ensure_inside(base, target) == target.resolve()


def test_traversal_is_rejected(tmp_path):
    base = tmp_path / "work"
    base.mkdir()
    (tmp_path / "outside.mp4").write_bytes(b"data")
    with pytest.raises(InvalidInput):
        ensure_inside(base, base / ".." / "outside.mp4")


def test_absolute_outside_path_is_rejected(tmp_path):
    base = tmp_path / "work"
    base.mkdir()
    outside = tmp_path / "elsewhere" / "video.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"data")
    with pytest.raises(InvalidInput):
        ensure_inside(base, outside)
