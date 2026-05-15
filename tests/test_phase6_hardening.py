"""
Phase 6 tests — Hardening.

Covers:
  1. Structured JSON logging (action_agent/utils/logging.py)
"""
from __future__ import annotations

import io
import json
import logging

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Structured JSON Logging
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_logger_returns_logger():
    """get_logger(name) returns a standard logging.Logger instance."""
    from action_agent.utils.logging import get_logger
    logger = get_logger("test.phase6")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test.phase6"


def test_get_logger_same_name_returns_same_logger():
    """Calling get_logger with the same name returns the same logger instance."""
    from action_agent.utils.logging import get_logger
    logger1 = get_logger("test.singleton")
    logger2 = get_logger("test.singleton")
    assert logger1 is logger2


def test_log_output_is_valid_json():
    """Each log line emitted by the structured logger is valid JSON."""
    from action_agent.utils.logging import get_logger

    stream = io.StringIO()
    logger = get_logger("test.json_output")

    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    logger.info("hello structured world")

    output = stream.getvalue().strip()
    assert output, "Logger produced no output"

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        assert isinstance(parsed, dict)


def test_log_line_contains_required_fields():
    """Each JSON log line contains level, timestamp, message, and logger fields."""
    from action_agent.utils.logging import get_logger

    stream = io.StringIO()
    logger = get_logger("test.fields")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    logger.warning("checking fields")

    output = stream.getvalue().strip()
    assert output, "Logger produced no output"

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        assert "level" in parsed, f"Missing 'level' field: {parsed}"
        assert "timestamp" in parsed, f"Missing 'timestamp' field: {parsed}"
        assert "message" in parsed, f"Missing 'message' field: {parsed}"
        assert "logger" in parsed, f"Missing 'logger' field: {parsed}"


def test_log_level_field_reflects_actual_level():
    """The level field in JSON output matches the actual log level used."""
    from action_agent.utils.logging import get_logger

    stream = io.StringIO()
    logger = get_logger("test.level_field")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    logger.warning("this is a warning")

    output = stream.getvalue().strip()
    parsed = json.loads(output.splitlines()[-1])
    assert parsed["level"].upper() in ("WARNING", "WARN")


def test_log_node_event_emits_node_field():
    """log_node_event emits a JSON line that includes a 'node' field."""
    from action_agent.utils.logging import get_logger, log_node_event

    stream = io.StringIO()
    logger = get_logger("test.node_event")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    log_node_event(logger, node_name="dispatch_local", event="started")

    output = stream.getvalue().strip()
    assert output, "log_node_event produced no output"

    parsed = json.loads(output.splitlines()[-1])
    assert "node" in parsed, f"Missing 'node' field in log_node_event output: {parsed}"
    assert parsed["node"] == "dispatch_local"


def test_log_node_event_includes_base_fields():
    """log_node_event output still contains all required base fields."""
    from action_agent.utils.logging import get_logger, log_node_event

    stream = io.StringIO()
    logger = get_logger("test.node_event_fields")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    log_node_event(logger, node_name="dispatch_local", event="complete")

    output = stream.getvalue().strip()
    parsed = json.loads(output.splitlines()[-1])
    for field in ("level", "timestamp", "message", "logger", "node"):
        assert field in parsed, f"Missing '{field}' field: {parsed}"


def test_log_message_field_contains_event():
    """The message field in log_node_event output includes the event string."""
    from action_agent.utils.logging import get_logger, log_node_event

    stream = io.StringIO()
    logger = get_logger("test.node_event_message")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    log_node_event(logger, node_name="dispatch_local", event="retry_attempt")

    output = stream.getvalue().strip()
    parsed = json.loads(output.splitlines()[-1])
    assert "retry_attempt" in parsed["message"] or "retry_attempt" in str(parsed)
