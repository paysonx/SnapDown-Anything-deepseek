"""运行配置：读取环境变量与 .env，集中所有可调参数。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_COOLDOWNS = {"bilibili": 3.0, "douyin": 5.0, "youtube": 3.0}


def load_dotenv(path: Path) -> None:
    """极简 .env 读取：不覆盖已存在的环境变量（环境变量优先级更高）。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _parse_cooldowns(raw: str | None) -> dict[str, float]:
    if not raw:
        return dict(DEFAULT_COOLDOWNS)
    result = dict(DEFAULT_COOLDOWNS)
    for chunk in raw.split(","):
        if ":" not in chunk:
            continue
        name, seconds = chunk.split(":", 1)
        name = name.strip().lower()
        try:
            result[name] = max(0.0, float(seconds))
        except ValueError:
            continue
    return result


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = BASE_DIR / ".data"
    web_dist: Path = BASE_DIR / "web" / "dist"
    proxy_mode: str = "auto"  # auto | local | server | off
    proxy_local: str = ""
    proxy_server: str = ""
    proxy_probe_url: str = "https://www.youtube.com/generate_204"
    proxy_probe_timeout: float = 6.0
    proxy_ttl_s: float = 60.0
    proxy_failure_ttl_s: float = 15.0
    cooldowns: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_COOLDOWNS))
    max_active_tasks: int = 3
    max_input_chars: int = 2000
    file_ttl_hours: float = 24.0
    work_ttl_days: float = 7.0
    log_level: str = "INFO"
    user_agent: str = DEFAULT_USER_AGENT
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    dev_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "snapdown.db"

    def cooldown_for(self, platform: str) -> float:
        return float(self.cooldowns.get(platform, 3.0))

    @classmethod
    def load(cls, base_dir: Path | None = None) -> "Settings":
        base = base_dir or BASE_DIR
        load_dotenv(base / ".env")
        data_dir = Path(os.environ.get("DATA_DIR") or (base / ".data")).resolve()
        web_dist = Path(os.environ.get("WEB_DIST") or (base / "web" / "dist")).resolve()
        mode = (os.environ.get("PROXY_MODE") or "auto").strip().lower()
        if mode not in {"auto", "local", "server", "off"}:
            mode = "auto"
        return cls(
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8787")),
            data_dir=data_dir,
            web_dist=web_dist,
            proxy_mode=mode,
            proxy_local=(os.environ.get("PROXY_LOCAL") or "").strip(),
            proxy_server=(os.environ.get("PROXY_SERVER") or "").strip(),
            proxy_probe_url=os.environ.get(
                "PROXY_PROBE_URL", "https://www.youtube.com/generate_204"
            ).strip(),
            proxy_probe_timeout=float(os.environ.get("PROXY_PROBE_TIMEOUT", "6")),
            cooldowns=_parse_cooldowns(os.environ.get("COOLDOWN_SECONDS")),
            max_active_tasks=int(os.environ.get("MAX_ACTIVE_TASKS", "3")),
            max_input_chars=int(os.environ.get("MAX_INPUT_CHARS", "2000")),
            file_ttl_hours=float(os.environ.get("FILE_TTL_HOURS", "24")),
            work_ttl_days=float(os.environ.get("WORK_TTL_DAYS", "7")),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            user_agent=os.environ.get("USER_AGENT", DEFAULT_USER_AGENT),
            ffmpeg_path=os.environ.get("FFMPEG_PATH", "").strip(),
            ffprobe_path=os.environ.get("FFPROBE_PATH", "").strip(),
            dev_origins=tuple(
                origin.strip()
                for origin in os.environ.get(
                    "DEV_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
                ).split(",")
                if origin.strip()
            ),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings


def reset_settings_cache() -> None:
    """测试用：清掉单例，允许重新读取环境变量。"""
    global _settings
    _settings = None
