"""Tests for stderr-only human and JSON logging configuration."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest

import h3c_hcl_mcp.infrastructure.logging as logging_module

_THIRD_PARTY_LOGGERS = (
    "asyncio",
    "urllib3",
    "httpx",
    "httpcore",
    "mcp.server.lowlevel.server",
    "telnetlib",
)


@pytest.fixture(autouse=True)
def restore_logging_state() -> Iterator[None]:
    """Keep root and third-party logger mutations local to each test."""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_root_level = root.level
    original_levels = {name: logging.getLogger(name).level for name in _THIRD_PARTY_LOGGERS}
    yield
    for handler in list(root.handlers):
        if handler not in original_handlers:
            handler.close()
    root.handlers[:] = original_handlers
    root.setLevel(original_root_level)
    for name, level in original_levels.items():
        logging.getLogger(name).setLevel(level)


def test_setup_logging_replaces_handlers_and_writes_human_logs_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    stale_handler = logging.NullHandler()
    root = logging.getLogger()
    root.addHandler(stale_handler)
    monkeypatch.setattr(logging_module.sys, "stderr", stream)

    logging_module.setup_logging("debug")
    logging.getLogger("tests.human").debug("diagnostic message")

    output = stream.getvalue()
    assert stale_handler not in root.handlers
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)
    assert root.handlers[0].stream is stream
    assert root.level == logging.DEBUG
    assert "Logging initialized level=DEBUG stderr=true" in output
    assert "[DEBUG] tests.human: diagnostic message" in output


def test_setup_logging_invalid_level_falls_back_to_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)

    logging_module.setup_logging("not-a-level")
    logging.getLogger("tests.level").debug("must not appear")
    logging.getLogger("tests.level").info("visible")

    assert logging.getLogger().level == logging.INFO
    assert "must not appear" not in stream.getvalue()
    assert "tests.level: visible" in stream.getvalue()


def test_setup_logging_json_includes_unicode_and_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)
    logging_module.setup_logging("DEBUG", format_json=True)

    try:
        raise ValueError("synthetic failure")
    except ValueError:
        logging.getLogger("tests.json").exception("设备检查失败")

    entries = [json.loads(line) for line in stream.getvalue().splitlines()]
    event = next(entry for entry in entries if entry["logger"] == "tests.json")
    assert event["level"] == "ERROR"
    assert event["message"] == "设备检查失败"
    assert event["exception"] == "synthetic failure"
    assert "T" in event["timestamp"]


def test_setup_logging_silences_known_third_party_loggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logging_module.sys, "stderr", io.StringIO())
    for name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)

    logging_module.setup_logging("DEBUG")

    assert all(logging.getLogger(name).level == logging.WARNING for name in _THIRD_PARTY_LOGGERS)


def test_setup_logging_bounds_client_controlled_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)
    logging_module.setup_logging("INFO")

    truncation_marker = "SHOULD_NOT_REACH_THE_LOG"
    logging.getLogger("mcp.server.lowlevel.server").warning(
        "Tool '%s' not listed",
        "x" * 20_000 + truncation_marker,
    )

    output = stream.getvalue()
    assert truncation_marker not in output
    assert "…' not listed" in output
    assert len(output) < 2_000


@pytest.mark.parametrize("format_json", [False, True])
def test_setup_logging_redacts_and_bounds_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    format_json: bool,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)
    logging_module.setup_logging("INFO", format_json=format_json)

    truncation_marker = "SHOULD_NOT_REACH_THE_LOG"
    try:
        raise RuntimeError("x" * 5_000 + truncation_marker)
    except RuntimeError:
        logging.getLogger("tests.exception-boundary").exception("bounded failure")

    output = stream.getvalue()
    assert truncation_marker not in output
    assert len(output) < 3_000
    assert "bounded failure" in output


def test_get_logger_returns_named_standard_logger() -> None:
    logger = logging_module.get_logger("h3c_hcl_mcp.tests")

    assert logger is logging.getLogger("h3c_hcl_mcp.tests")
    assert logger.name == "h3c_hcl_mcp.tests"
