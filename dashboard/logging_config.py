"""Structured application logging with correlation context and safe redaction."""

from __future__ import annotations

import json
import logging
import os
import re
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")
RECENT_ERRORS: deque[dict[str, Any]] = deque(maxlen=50)
SENSITIVE_KEYS = ("password", "secret", "token", "authorization", "cookie", "private_key", "pwd")


def redact(value: Any, key: str = "") -> Any:
    if any(fragment in key.lower() for fragment in SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)(password|secret|token|pwd)=([^;\s]+)", r"\1=[REDACTED]", value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", correlation_id.get()),
            **redact(getattr(record, "fields", {})),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), separators=(",", ":"), default=str)


class RecentErrorHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            return
        RECENT_ERRORS.appendleft({
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", correlation_id.get()),
        })


def configure_logging() -> None:
    level = getattr(logging, os.getenv("MES_LOG_LEVEL", "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    stream = logging.StreamHandler()
    stream.setFormatter(JsonFormatter())
    root.addHandler(stream)
    root.addHandler(RecentErrorHandler())
    root.setLevel(level)

    # The OPC UA dependency emits every protocol operation at INFO. Preserve
    # its warnings and errors without drowning out the dashboard request logs.
    for logger_name in ("asyncua", "asyncio"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def recent_errors() -> list[dict[str, Any]]:
    return list(RECENT_ERRORS)
