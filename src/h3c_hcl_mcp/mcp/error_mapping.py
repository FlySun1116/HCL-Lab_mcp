"""Map domain errors to structured MCP error responses.

Domain errors are raised as ToolError so MCP sets isError=true
while preserving the structured error payload in the error text.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any, cast

from mcp.server.fastmcp.exceptions import ToolError

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.result import ToolResult

logger = logging.getLogger(__name__)

_PATH_DETAIL_KEYS = {"path", "project_path", "config_path", "file_path"}
_UNTRUSTED_OUTPUT_DETAIL_KEYS = {
    "banner",
    "buffer_tail",
    "device_output",
    "raw_output",
    "transcript",
}
_PATH_SAFE_MESSAGES = {
    ErrorCode.PROJECT_NOT_FOUND: "HCL project metadata was not found",
    ErrorCode.PROJECT_DAMAGED: "HCL project data is damaged or unreadable",
    ErrorCode.PROJECT_PATH_TRAVERSAL: "HCL project path is not allowed",
}
_NEXT_ACTIONS = {
    ErrorCode.HCL_NOT_INSTALLED: (
        "Install HCL 5.10.x separately, or configure hcl.install_dir to an existing installation."
    ),
    ErrorCode.PROJECT_NOT_FOUND: (
        "Configure hcl.projects_dirs with the parent directory of the HCL project, then retry."
    ),
    ErrorCode.DEVICE_NOT_RUNNING: (
        "Open the project in HCL, start the target device, wait for its console, then retry."
    ),
    ErrorCode.CONSOLE_UNAVAILABLE: (
        "Confirm the device is running and HCL created its loopback console, then retry."
    ),
    ErrorCode.CONSOLE_PORT_UNKNOWN: (
        "Restart the device console in HCL and wait for a project-bound console log entry."
    ),
    ErrorCode.OUTPUT_TOO_LARGE: ("Narrow the request or increase server.max_tool_result_bytes, then retry."),
}


def structured_error_payload(
    *,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable error payload exposed to MCP clients.

    ``request_id`` deliberately lives inside the ``error`` object.  FastMCP
    serializes :class:`ToolError` as error content rather than as a normal
    ``ToolResult`` envelope, so keeping the identifier only on ToolResult
    would make failed calls impossible to correlate with the audit trail.
    """
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if details:
        error.update(details)
    return {"error": error}


def extract_structured_error(error: BaseException) -> dict[str, Any] | None:
    """Extract our JSON error object from a ToolError exception chain.

    FastMCP may prefix a nested ToolError with ``Error executing tool ...``.
    This parser intentionally looks only for JSON objects containing an
    ``error`` mapping; it never exposes arbitrary exception text to clients.
    """
    decoder = json.JSONDecoder()
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current)
        for offset, character in enumerate(message):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(message[offset:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and isinstance(candidate.get("error"), dict):
                return cast(dict[str, Any], candidate["error"])
        current = current.__cause__ or current.__context__
    return None


def map_domain_error(error: DomainError, request_id: str) -> ToolResult:
    """Map a DomainError to a ToolResult.failure().

    Also raises ToolError so the MCP response has isError=true.
    The structured error is serialized as JSON in the ToolError message.

    Args:
        error: The domain error to map.
        request_id: The MCP request ID for tracing.

    Raises:
        ToolError: Always, to set MCP isError=true.
    """
    logger.warning("Mapping domain error: code=%s request_id=%s", error.code.value, request_id)

    message, details = _public_domain_error(error)

    # Raise ToolError to set MCP isError=true with structured error payload
    error_payload = structured_error_payload(
        code=error.code.value,
        message=message,
        request_id=request_id,
        details=details,
    )
    raise ToolError(json.dumps(error_payload)) from error


def _public_domain_error(error: DomainError) -> tuple[str, dict[str, Any] | None]:
    """Remove filesystem locations from errors crossing the MCP boundary."""
    details = dict(error.details) if error.details else {}
    removed_path = any(key in details for key in _PATH_DETAIL_KEYS)
    for key in _PATH_DETAIL_KEYS:
        details.pop(key, None)
    for key in _UNTRUSTED_OUTPUT_DETAIL_KEYS:
        details.pop(key, None)

    message = error.message
    if removed_path:
        message = _PATH_SAFE_MESSAGES.get(error.code, error.code.value)
    next_action = _NEXT_ACTIONS.get(error.code)
    if next_action:
        details.setdefault("next_action", next_action)
    return message, details or None


def handle_errors[**P, R](
    fn: Callable[P, R] | None = None,
    *,
    request_id_arg: str = "request_id",
) -> Any:
    """Decorator that wraps a tool function with DomainError handling.

    Usage:
        @handle_errors
        async def my_tool(...) -> ToolResult:
            ...

    When a DomainError is raised inside the decorated function, it is
    automatically converted to a ToolError (which sets MCP isError=true).

    Args:
        request_id_arg: Name of the keyword argument containing the request_id.
                        If the function has no such arg, a UUID is generated.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, Any]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except DomainError as e:
                rid = str(kwargs.get(request_id_arg, str(uuid.uuid4())))
                return map_domain_error(e, rid)

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except DomainError as e:
                rid = str(kwargs.get(request_id_arg, str(uuid.uuid4())))
                return map_domain_error(e, rid)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def internal_error(request_id: str, message: str = "Internal server error") -> ToolResult:
    """Create a ToolResult for unexpected internal errors.

    Use this in broad except clauses to catch non-DomainError exceptions.
    Raises ToolError to set MCP isError=true.
    """
    logger.exception("Internal error: %s [request_id=%s]", message, request_id)
    error_payload = structured_error_payload(
        code=ErrorCode.INTERNAL_ERROR.value,
        message=message,
        request_id=request_id,
    )
    raise ToolError(json.dumps(error_payload))


def not_implemented(request_id: str, feature: str = "") -> ToolResult:
    """Create a ToolResult for features not yet implemented.

    Raises ToolError to set MCP isError=true.
    """
    msg = f"Not implemented: {feature}" if feature else "Not implemented"
    error_payload = structured_error_payload(
        code=ErrorCode.NOT_IMPLEMENTED.value,
        message=msg,
        request_id=request_id,
    )
    raise ToolError(json.dumps(error_payload))
