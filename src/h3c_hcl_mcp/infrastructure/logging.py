"""Stderr logging setup for the MCP server.

All logs MUST go to stderr. stdout is reserved for MCP JSON-RPC messages.
Never use print() or stdout logging in production code.
"""

from __future__ import annotations

import logging
import sys
from typing import Any


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

    if format_json:
        formatter = _JSONFormatter()
    else:
        formatter = logging.Formatter(
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
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module.

    Convenience wrapper — ensures consistent logger naming.
    """
    return logging.getLogger(name)
