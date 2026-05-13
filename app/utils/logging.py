from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any


RESERVED_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}

SECRET_VALUE_PATTERNS = [
    re.compile(r"bot\d+:[A-Za-z0-9_-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
]


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for structured application logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }

        for key, value in record.__dict__.items():
            if key in RESERVED_LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            if "token" in key.lower() or "secret" in key.lower() or "key" in key.lower():
                payload[key] = "[redacted]"
            else:
                payload[key] = redact(value) if isinstance(value, str) else value

        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def redact(value: str) -> str:
    for pattern in SECRET_VALUE_PATTERNS:
        value = pattern.sub("[redacted]", value)
    return value
