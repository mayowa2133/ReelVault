from __future__ import annotations

import re


class ReelVaultError(Exception):
    """Base application error with safe metadata for logs and responses."""

    def __init__(self, message: str, *, code: str = "reelvault_error", step: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.step = step


class ExternalServiceError(ReelVaultError):
    def __init__(self, message: str, *, step: str | None = None):
        super().__init__(message, code="external_service_error", step=step)


class DownloadFailedError(ReelVaultError):
    def __init__(self, message: str, *, step: str | None = None):
        super().__init__(message, code="download_failed", step=step)


class FileProcessingError(ReelVaultError):
    def __init__(self, message: str, *, step: str | None = None):
        super().__init__(message, code="file_processing_error", step=step)


class TelegramSendError(ReelVaultError):
    def __init__(self, message: str, *, step: str | None = None):
        super().__init__(message, code="telegram_send_error", step=step)


SECRET_PATTERNS = [
    re.compile(r"bot\d+:[A-Za-z0-9_-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
]


def public_error_message(exc: BaseException) -> str:
    message = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
    message = message.replace("\n", " ").strip()
    for pattern in SECRET_PATTERNS:
        message = pattern.sub("[redacted]", message)
    return message[:1000]

