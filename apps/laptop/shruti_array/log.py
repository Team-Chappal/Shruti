"""Structured logging setup for SHRUTI.

Every component on the laptop processor uses this logger so we get
a single, consistent log format. Run with `SHRUTI_LOG_FORMAT=json`
to get machine-readable JSON lines (for shipping to a log
aggregator); the default is a human-readable format for the
demo.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any


_HUMAN_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record. Safe for structured pipelines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime(_DATE_FORMAT, time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach any extra= fields the caller passed.
        for key, value in record.__dict__.items():
            if key in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
                "taskName",
            ):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


def configure_logging(level: str | int = "INFO") -> None:
    """Configure the root logger once. Idempotent: safe to call from
    multiple entry points (CLI, library import)."""
    root = logging.getLogger()
    if getattr(root, "_shruti_configured", False):
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stderr)
    if os.environ.get("SHRUTI_LOG_FORMAT", "").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_HUMAN_FORMAT, datefmt=_DATE_FORMAT))
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root._shruti_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
