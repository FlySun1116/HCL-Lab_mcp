"""Stderr logging setup for the MCP server.

All logs MUST go to stderr. stdout is reserved for MCP JSON-RPC messages.
Never use print() or stdout logging in production code.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

from h3c_hcl_mcp.infrastructure.audit.redact import redact_sensitive

_MAX_LOG_ARGUMENT_CHARS = 1024
_MAX_LOG_EXCEPTION_CHARS = 1024
_LOCAL_PATH_MARKER = "<local-path>"
_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    r"""(["'])(?:[A-Za-z]:[\\/]|\\\\|/).*?\1""",
    re.IGNORECASE,
)
_FILE_URI_PATH_RE = re.compile(
    r"""(?<![A-Za-z0-9_])file://[^\s"'<>|]+""",
    re.IGNORECASE,
)
_FORWARD_UNC_PATH_RE = re.compile(
    r"""(?<![A-Za-z0-9_:/])//[^/\s"'<>|]+/[^\s"'<>|]+""",
)
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]|\\\\)[^\r\n\t]*?"
    r"(?=(?:;\s*|,\s+|\s+[A-Za-z_][A-Za-z0-9_.-]*=|$))",
    re.IGNORECASE,
)
_POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"""(?<![A-Za-z0-9_:/])/(?!/)[^\s"'<>|]+""",
)


def setup_logging(level: str = "INFO", *, format_json: bool = False) -> None:
    """Configure logging to stderr for the MCP server process.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        format_json: If True, emit JSON-formatted log lines for machine
            consumption. If False, emit human-readable text.

    Rules:
    - All logs go to stderr (never stdout).
    - The handler is created with stream=sys.stderr.
    - Existing root handlers are replaced to avoid duplicates.
    - Third-party library loggers are set to WARNING to reduce noise.
    """
    root = logging.getLogger()
    # Remove any existing handlers to avoid duplication on re-init
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_BoundedLogArgumentsFilter())

    formatter: logging.Formatter
    if format_json:
        formatter = _JSONFormatter()
    else:
        formatter = _BoundedExceptionFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Silence noisy third-party libraries
    _silence_third_party_loggers()

    # Log startup confirmation
    logger = logging.getLogger(__name__)
    logger.info("Logging initialized level=%s stderr=true", level.upper())


def _silence_third_party_loggers() -> None:
    """Set third-party loggers to WARNING to reduce noise."""
    noisy = [
        "asyncio",
        "urllib3",
        "httpx",
        "httpcore",
        "mcp.server.lowlevel.server",
        "telnetlib",
    ]
    for name in noisy:
        logging.getLogger(name).setLevel(logging.WARNING)


class _JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt or "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = _bounded_exception_text(str(record.exc_info[1]))
        return json.dumps(log_entry, ensure_ascii=False)


class _BoundedExceptionFormatter(logging.Formatter):
    """Redact and bound human-readable exception tracebacks."""

    def formatException(self, exc_info: Any) -> str:  # noqa: N802
        return _bounded_exception_text(super().formatException(exc_info))


class _BoundedLogArgumentsFilter(logging.Filter):
    """Bound client-controlled string arguments before formatter expansion."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _sanitize_log_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_bounded_log_argument(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _bounded_log_argument(value) for key, value in record.args.items()}
        return True


def _bounded_log_argument(value: object) -> object:
    if isinstance(value, os.PathLike):
        return _LOCAL_PATH_MARKER
    if isinstance(value, BaseException):
        return type(value).__name__
    if not isinstance(value, str):
        return value
    redacted = _sanitize_log_text(value)
    if len(redacted) <= _MAX_LOG_ARGUMENT_CHARS:
        return redacted
    return redacted[: _MAX_LOG_ARGUMENT_CHARS - 1] + "…"


def _bounded_exception_text(value: str) -> str:
    redacted = _sanitize_log_text(value)
    if len(redacted) <= _MAX_LOG_EXCEPTION_CHARS:
        return redacted
    return redacted[: _MAX_LOG_EXCEPTION_CHARS - 1] + "…"


def _sanitize_log_text(value: str) -> str:
    """Remove credentials and absolute host paths from log text."""

    redacted = redact_sensitive(value)
    redacted = _QUOTED_ABSOLUTE_PATH_RE.sub(_LOCAL_PATH_MARKER, redacted)
    redacted = _FILE_URI_PATH_RE.sub(f"file://{_LOCAL_PATH_MARKER}", redacted)
    redacted = _FORWARD_UNC_PATH_RE.sub(_LOCAL_PATH_MARKER, redacted)
    redacted = _WINDOWS_ABSOLUTE_PATH_RE.sub(_LOCAL_PATH_MARKER, redacted)
    return _POSIX_ABSOLUTE_PATH_RE.sub(_LOCAL_PATH_MARKER, redacted)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module.

    Convenience wrapper — ensures consistent logger naming.
    """
    return logging.getLogger(name)
