"""SQLite 持久化（WAL）。任务状态与最近进度落盘，服务重启不丢。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .models import (
    Platform,
    Progress,
    QualityOption,
    Route,
    Task,
    TaskStatus,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    platform      TEXT NOT NULL,
    route         TEXT NOT NULL,
    status        TEXT NOT NULL,
    status_reason TEXT,
    title         TEXT,
    duration_s    REAL,
    uploader      TEXT,
    options_json  TEXT NOT NULL DEFAULT '[]',
    selected_option TEXT,
    progress_json TEXT NOT NULL DEFAULT '{}',
    error_code    TEXT,
    error_message TEXT,
    retryable     INTEGER NOT NULL DEFAULT 0,
    work_dir      TEXT,
    output_path   TEXT,
    output_size   INTEGER,
    attempts      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    started_at    REAL,
    finished_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status  ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);
"""

_COLUMNS = (
    "url",
    "platform",
    "route",
    "status",
    "status_reason",
    "title",
    "duration_s",
    "uploader",
    "options_json",
    "selected_option",
    "progress_json",
    "error_code",
    "error_message",
    "retryable",
    "work_dir",
    "output_path",
    "output_size",
    "attempts",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
)

# 允许调用方直接用模型字段名写入（jobs 层按 Task 字段传参）
_FIELD_ALIASES = {"options": "options_json", "progress": "progress_json"}


def _encode(key: str, value: Any) -> Any:
    if key == "status" and isinstance(value, TaskStatus):
        return value.value
    if key == "platform" and isinstance(value, Platform):
        return value.value
    if key == "route" and isinstance(value, Route):
        return value.value
    if key == "options_json" and isinstance(value, list):
        return json.dumps(
            [item.to_dict() if isinstance(item, QualityOption) else item for item in value],
            ensure_ascii=False,
        )
    if key == "progress_json" and isinstance(value, Progress):
        return json.dumps(value.to_dict(), ensure_ascii=False)
    if key == "retryable":
        return int(bool(value))
    return value


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        url=row["url"],
        platform=Platform(row["platform"]),
        route=Route(row["route"]),
        status=TaskStatus(row["status"]),
        status_reason=row["status_reason"],
        title=row["title"],
        duration_s=row["duration_s"],
        uploader=row["uploader"],
        options=[QualityOption.from_dict(item) for item in json.loads(row["options_json"] or "[]")],
        selected_option=row["selected_option"],
        progress=Progress.from_dict(json.loads(row["progress_json"] or "{}")),
        error_code=row["error_code"],
        error_message=row["error_message"],
        retryable=bool(row["retryable"]),
        work_dir=row["work_dir"],
        output_path=row["output_path"],
        output_size=row["output_size"],
        attempts=row["attempts"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()

    # -- 连接 ---------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)

    # -- 写 ----------------------------------------------------------------
    def create(self, task: Task) -> None:
        values = {
            "id": task.id,
            "url": task.url,
            "platform": task.platform,
            "route": task.route,
            "status": task.status,
            "status_reason": task.status_reason,
            "title": task.title,
            "duration_s": task.duration_s,
            "uploader": task.uploader,
            "options_json": task.options,
            "selected_option": task.selected_option,
            "progress_json": task.progress,
            "error_code": task.error_code,
            "error_message": task.error_message,
            "retryable": task.retryable,
            "work_dir": task.work_dir,
            "output_path": task.output_path,
            "output_size": task.output_size,
            "attempts": task.attempts,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        }
        keys = ["id", *_COLUMNS]
        placeholders = ", ".join("?" for _ in keys)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"INSERT INTO tasks ({', '.join(keys)}) VALUES ({placeholders})",
                [_encode(key, values[key]) for key in keys],
            )

    def update(self, task_id: str, **fields: Any) -> None:
        fields = {_FIELD_ALIASES.get(key, key): value for key, value in fields.items()}
        unknown = set(fields) - set(_COLUMNS)
        if unknown:
            raise ValueError(f"未知字段: {sorted(unknown)}")
        fields.setdefault("updated_at", time.time())
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ?",
                [_encode(key, value) for key, value in fields.items()] + [task_id],
            )

    # -- 读 ----------------------------------------------------------------
    def get(self, task_id: str) -> Task | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def list_tasks(
        self, *, limit: int = 50, statuses: Iterable[TaskStatus] | None = None
    ) -> list[Task]:
        sql = "SELECT * FROM tasks"
        params: list[Any] = []
        if statuses:
            values = [status.value for status in statuses]
            sql += f" WHERE status IN ({', '.join('?' for _ in values)})"
            params.extend(values)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_task(row) for row in rows]

    def find_active_by_url(self, url: str) -> Task | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE url = ? AND status IN "
                "('resolve_queued','resolving','awaiting_selection','download_queued',"
                "'downloading','merging') ORDER BY created_at DESC LIMIT 1",
                (url,),
            ).fetchone()
        return _row_to_task(row) if row else None

    def count_active(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE status IN "
                "('resolve_queued','resolving','download_queued','downloading','merging')"
            ).fetchone()
        return int(row["n"])

    # -- 生命周期 ----------------------------------------------------------
    def mark_interrupted(self, reason: str) -> int:
        """服务重启：把上次未完成的任务标记为已中断。"""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'interrupted', status_reason = ?, "
                "error_code = 'INTERRUPTED', error_message = ?, retryable = 1, "
                "updated_at = ? WHERE status IN "
                "('resolve_queued','resolving','download_queued','downloading','merging')",
                (reason, reason, time.time()),
            )
            return cursor.rowcount

    def delete(self, task_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def terminal_before(self, cutoff: float, *, limit: int = 200) -> list[Task]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status IN "
                "('completed','cancelled','failed','interrupted') "
                "AND updated_at < ? ORDER BY updated_at ASC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        return [_row_to_task(row) for row in rows]
