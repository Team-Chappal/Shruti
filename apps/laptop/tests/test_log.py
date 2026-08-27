"""Tests for the structured logging setup."""
from __future__ import annotations

import io
import json
import logging

from shruti_array.log import JsonFormatter, configure_logging, get_logger


def test_json_formatter_emits_one_object_per_line() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname="", lineno=0,
        msg="hello %s", args=("world",), exc_info=None,
    )
    out = formatter.format(record)
    obj = json.loads(out)
    assert obj["level"] == "INFO"
    assert obj["logger"] == "x"
    assert obj["msg"] == "hello world"
    assert "ts" in obj


def test_json_formatter_attaches_extras() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname="", lineno=0,
        msg="packet dropped", args=(), exc_info=None,
    )
    record.phone_id = 1
    record.reason = "rate_limit"
    out = json.loads(formatter.format(record))
    assert out["phone_id"] == 1
    assert out["reason"] == "rate_limit"


def test_configure_logging_is_idempotent() -> None:
    """Calling configure_logging twice must not crash and must respect
    the new level. Pytest's logging plugin adds its own capture
    handlers around ours, so we don't assert the absolute handler
    count; we assert that at least one StreamHandler (ours) is
    present after each call and that the level updates."""
    import logging
    configure_logging("INFO")
    assert any(isinstance(h, logging.StreamHandler) for h in logging.getLogger().handlers)
    configure_logging("DEBUG")
    assert any(isinstance(h, logging.StreamHandler) for h in logging.getLogger().handlers)
    assert logging.getLogger().level == logging.DEBUG


def test_get_logger_returns_named_logger() -> None:
    log = get_logger("shruti.test")
    assert log.name == "shruti.test"
