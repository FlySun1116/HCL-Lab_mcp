"""Tests for stderr-only human and JSON logging configuration."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from pathlib import PureWindowsPath

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
def test_setup_logging_redacts_absolute_host_paths(
    monkeypatch: pytest.MonkeyPatch,
    format_json: bool,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)
    logging_module.setup_logging("INFO", format_json=format_json)

    windows_path = PureWindowsPath("C:/Users/example/private/audit.db")
    windows_text = "D:\\Labs\\private\\project.net"
    posix_path = "/home/example/private/audit.db"
    system_path = "/etc/hcl/private.log"
    install_path = "/usr/local/hcl/config.yaml"
    custom_path = "/custom-lab/runtime/console.log"
    file_uri = "file:///var/lib/hcl/private.log"
    localhost_file_uri = "file://localhost/var/lib/hcl/private.log"
    authority_file_uri = "file://server/share/private/audit.db"
    forward_unc = "//server/share/private/audit.db"
    root_relative_route = "/api/v1/health"
    logging.getLogger("tests.paths").warning(
        "local files: %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, and %s",
        windows_path,
        windows_text,
        posix_path,
        system_path,
        install_path,
        custom_path,
        file_uri,
        localhost_file_uri,
        authority_file_uri,
        forward_unc,
        root_relative_route,
    )

    output = stream.getvalue()
    assert "C:/Users" not in output
    assert "D:\\Labs" not in output
    assert "/home/example" not in output
    assert "/etc/hcl" not in output
    assert "/usr/local/hcl" not in output
    assert "/custom-lab" not in output
    assert "/var/lib/hcl" not in output
    assert "file://localhost" not in output
    assert "file://server/share" not in output
    assert "//server/share" not in output
    assert "/api/v1/health" not in output
    assert output.count("<local-path>") >= 11


@pytest.mark.parametrize("format_json", [False, True])
def test_setup_logging_preserves_diagnostics_after_windows_path(
    monkeypatch: pytest.MonkeyPatch,
    format_json: bool,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)
    logging_module.setup_logging("INFO", format_json=format_json)

    detail = "C:\\private\\audit.db; request=abc-123; url=https://example.com/api/v1"
    logging.getLogger("tests.path-suffix").warning("failure=%s", detail)

    output = stream.getvalue()
    assert "C:\\private" not in output
    assert "<local-path>" in output
    assert "request=abc-123" in output
    assert "https://example.com/api/v1" in output


@pytest.mark.parametrize("format_json", [False, True])
def test_setup_logging_redacts_paths_from_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    format_json: bool,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)
    logging_module.setup_logging("INFO", format_json=format_json)

    try:
        raise RuntimeError('failed at "C:\\Users\\example\\private\\audit.db"')
    except RuntimeError:
        logging.getLogger("tests.path-exception").exception("bounded failure")

    output = stream.getvalue()
    assert "C:\\Users" not in output
    assert "<local-path>" in output


@pytest.mark.parametrize("format_json", [False, True])
def test_setup_logging_preserves_https_urls(
    monkeypatch: pytest.MonkeyPatch,
    format_json: bool,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)
    logging_module.setup_logging("INFO", format_json=format_json)

    logging.getLogger("tests.url").info("documentation=%s", "https://example.com/api/v1")

    output = stream.getvalue()
    assert "https://example.com/api/v1" in output


@pytest.mark.parametrize("format_json", [False, True])
def test_setup_logging_redacts_compact_labelled_posix_paths(
    monkeypatch: pytest.MonkeyPatch,
    format_json: bool,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)
    logging_module.setup_logging("INFO", format_json=format_json)

    logging.getLogger("tests.compact-paths").warning(
        "path:/home/example/private.db config:/etc/hcl/private.yaml error at:/usr/local/private/key"
    )

    output = stream.getvalue()
    assert "/home/example" not in output
    assert "/etc/hcl" not in output
    assert "/usr/local/private" not in output
    assert output.count("<local-path>") >= 3


@pytest.mark.parametrize("format_json", [False, True])
def test_setup_logging_escapes_line_and_terminal_control_characters(
    monkeypatch: pytest.MonkeyPatch,
    format_json: bool,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(logging_module.sys, "stderr", stream)
    logging_module.setup_logging("INFO", format_json=format_json)

    logging.getLogger("tests.log-controls").error(
        "failed target=%s",
        "device-1\nFORGED level=CRITICAL\r\t\x1b[31m\x9b32m\u2028NEXT",
    )

    output = stream.getvalue()
    rendered = output
    if format_json:
        entries = [json.loads(line) for line in output.splitlines()]
        rendered = next(entry["message"] for entry in entries if entry["logger"] == "tests.log-controls")
    assert "device-1\\nFORGED level=CRITICAL\\r\\t\\x1b[31m\\x9b32m\\u2028NEXT" in rendered
    assert "\nFORGED" not in output
    assert "\x1b[31m" not in output
    assert "\x9b32m" not in output


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
