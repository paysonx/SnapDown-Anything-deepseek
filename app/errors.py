"""统一的业务异常，API 层据此返回结构化错误。"""

from __future__ import annotations


class AppError(Exception):
    """可预期的业务错误：带错误码、HTTP 状态与是否可重试。"""

    status_code = 400
    code = "BAD_REQUEST"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable

    def to_dict(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            }
        }


class InvalidInput(AppError):
    code = "INVALID_INPUT"
    status_code = 400


class UnsupportedPlatform(AppError):
    code = "UNSUPPORTED_PLATFORM"
    status_code = 422


class NotFound(AppError):
    code = "NOT_FOUND"
    status_code = 404


class Conflict(AppError):
    code = "CONFLICT"
    status_code = 409


class TooManyTasks(AppError):
    code = "TOO_MANY_TASKS"
    status_code = 429


class ProxyUnavailable(AppError):
    code = "PROXY_UNAVAILABLE"
    status_code = 503
    retryable = True


class ExtractionFailed(AppError):
    code = "EXTRACT_FAILED"
    status_code = 502
    retryable = True


class DownloadFailed(AppError):
    code = "DOWNLOAD_FAILED"
    status_code = 502
    retryable = True


class TaskCancelled(Exception):
    """控制流异常：由进度钩子抛出以中止 yt-dlp。"""
