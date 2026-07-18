"""Stable domain error codes.

All errors that cross module boundaries must use these codes.
Adapters convert third-party exceptions into these errors.
The MCP layer maps these to structured tool results.
"""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Machine-readable error codes — stable across versions."""

    # ---- Project & Discovery ----
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PROJECT_DAMAGED = "PROJECT_DAMAGED"
    PROJECT_PATH_TRAVERSAL = "PROJECT_PATH_TRAVERSAL"

    # ---- Device ----
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_NOT_RUNNING = "DEVICE_NOT_RUNNING"
    DEVICE_AMBIGUOUS = "DEVICE_AMBIGUOUS"

    # ---- Console / Transport ----
    CONSOLE_UNAVAILABLE = "CONSOLE_UNAVAILABLE"
    CONSOLE_PORT_UNKNOWN = "CONSOLE_PORT_UNKNOWN"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    CONNECTION_CLOSED = "CONNECTION_CLOSED"
    PROMPT_TIMEOUT = "PROMPT_TIMEOUT"
    PROMPT_CHANGED = "PROMPT_CHANGED"

    # ---- Command Execution ----
    COMMAND_DENIED = "COMMAND_DENIED"
    COMMAND_NOT_ALLOWED = "COMMAND_NOT_ALLOWED"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    COMMAND_OUTPUT_TRUNCATED = "COMMAND_OUTPUT_TRUNCATED"
    COMMAND_PARSE_ERROR = "COMMAND_PARSE_ERROR"

    # ---- Configuration Change ----
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_INVALID = "APPROVAL_INVALID"
    BASELINE_CHANGED = "BASELINE_CHANGED"
    PLAN_EXPIRED = "PLAN_EXPIRED"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"

    # ---- Policy ----
    POLICY_DENIED = "POLICY_DENIED"
    WRITE_DISABLED = "WRITE_DISABLED"

    # ---- General ----
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    TIMEOUT = "TIMEOUT"
    OUTPUT_TOO_LARGE = "OUTPUT_TOO_LARGE"
    CONCURRENCY_CONFLICT = "CONCURRENCY_CONFLICT"
    HCL_NOT_INSTALLED = "HCL_NOT_INSTALLED"


class DomainError(Exception):
    """Base exception for all domain errors."""

    code: ErrorCode
    message: str
    details: dict[str, Any] | None

    def __init__(
        self,
        code: ErrorCode,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or code.value
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result
