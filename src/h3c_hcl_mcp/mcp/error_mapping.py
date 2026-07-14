"""Map domain errors to structured ToolResult responses.

Every tool should catch DomainError and convert to ToolResult.failure()
using the functions in this module.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.result import ToolResult

logger = logging.getLogger(__name__)


def map_domain_error(error: DomainError, request_id: str) -> ToolResult:
    """Map a DomainError to a ToolResult.failure().

    Args:
        error: The domain error to map.
        request_id: The MCP request ID for tracing.

    Returns:
        ToolResult with ok=False and structured error data.
    """
    logger.warning(
        "Mapping domain error: code=%s message=%s request_id=%s",
        error.code.value,
        error.message,
        request_id,
    )

    return ToolResult.failure(
        request_id=request_id,
        code=error.code.value,
        message=error.message,
        details=error.details,
    )


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
    automatically converted to a ToolResult.failure() response.

    Args:
        request_id_arg: Name of the keyword argument containing the request_id.
                        If the function has no such arg, a UUID is generated.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            try:
                return await func(*args, **kwargs)
            except DomainError as e:
                rid = kwargs.get(request_id_arg, str(uuid.uuid4()))
                return map_domain_error(e, rid)

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except DomainError as e:
                rid = kwargs.get(request_id_arg, str(uuid.uuid4()))
                return map_domain_error(e, rid)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    if fn is not None:
        return decorator(fn)
    return decorator


def internal_error(request_id: str, message: str = "Internal server error") -> ToolResult:
    """Create a ToolResult for unexpected internal errors.

    Use this in broad except clauses to catch non-DomainError exceptions.
    """
    logger.exception("Internal error: %s [request_id=%s]", message, request_id)
    return ToolResult.failure(
        request_id=request_id,
        code=ErrorCode.INTERNAL_ERROR.value,
        message=message,
    )


def not_implemented(request_id: str, feature: str = "") -> ToolResult:
    """Create a ToolResult for features not yet implemented."""
    msg = f"Not implemented: {feature}" if feature else "Not implemented"
    return ToolResult.failure(
        request_id=request_id,
        code=ErrorCode.NOT_IMPLEMENTED.value,
        message=msg,
    )
