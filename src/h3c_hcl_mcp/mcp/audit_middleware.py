"""Audit middleware — records every tool invocation to the audit sink.

Wraps tool functions to automatically record audit events for both
successful and failed calls.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from h3c_hcl_mcp.domain.audit import AuditEvent
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.mcp.error_mapping import extract_structured_error, structured_error_payload
from h3c_hcl_mcp.ports.audit_sink import AuditSink

logger = logging.getLogger(__name__)

_MAX_AUDIT_IDENTIFIER_CHARS = 256

_POLICY_ERROR_CODES = {
    "APPROVAL_EXPIRED",
    "APPROVAL_INVALID",
    "APPROVAL_REQUIRED",
    "COMMAND_DENIED",
    "COMMAND_NOT_ALLOWED",
    "POLICY_DENIED",
    "WRITE_DISABLED",
}


def with_audit(
    tool_name: str,
    audit_sink: AuditSink,
    caller: str = "mcp-client",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory that wraps a tool function with audit recording.

    Args:
        tool_name: The MCP tool name.
        audit_sink: The audit sink to record events to.
        caller: Caller identity for the audit record.

    Returns:
        A decorator that wraps a tool function with audit recording.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            import asyncio

            request_id = str(uuid.uuid4())
            start = time.monotonic()
            error_code = None
            policy_result = "allowed"
            change_summary = None
            cancelled = False

            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                response_request_id = _extract_result_request_id(result)
                if response_request_id:
                    request_id = response_request_id
                return result
            except DomainError as e:
                error_code = e.code.value
                policy_result = _policy_result_for_error(error_code)
                raise
            except ToolError as e:
                structured = extract_structured_error(e)
                if structured is not None:
                    structured_request_id = structured.get("request_id")
                    structured_code = structured.get("code")
                    if isinstance(structured_request_id, str) and structured_request_id:
                        request_id = structured_request_id
                    if isinstance(structured_code, str) and structured_code:
                        error_code = structured_code
                if error_code is None:
                    error_code = "INTERNAL_ERROR"
                policy_result = _policy_result_for_error(error_code)
                raise
            except Exception:
                error_code = "INTERNAL_ERROR"
                policy_result = "not_evaluated"
                raise
            except asyncio.CancelledError:
                # The ToolManager timeout boundary owns timeout mapping and
                # auditing. Avoid emitting a second, falsely successful event.
                cancelled = True
                raise
            finally:
                if not cancelled:
                    duration_ms = (time.monotonic() - start) * 1000
                    try:
                        event = AuditEvent(
                            event_id=str(uuid.uuid4()),
                            request_id=request_id,
                            caller=caller,
                            tool=tool_name,
                            target=_extract_target(kwargs),
                            policy_result=policy_result,
                            outcome="error" if error_code else "success",
                            change_summary=change_summary,
                            duration_ms=round(duration_ms, 2),
                            error_code=error_code,
                        )
                        await audit_sink.append(event)
                    except Exception as error:
                        # Auditing is a declared v0.1 invariant. A read-only
                        # result must not be reported as successful when its
                        # append-only evidence could not be persisted.
                        logger.error("Failed to append audit event for %s: %s", tool_name, error)
                        raise _audit_unavailable_error(request_id) from None

        return wrapper

    return decorator


def _extract_target(kwargs: dict[str, Any]) -> dict[str, object] | None:
    """Extract target info from tool kwargs."""
    project_id = kwargs.get("project_id")
    device_id = kwargs.get("device_id")
    if project_id is not None:
        target: dict[str, object] = {"project_id": _bounded_audit_text(project_id)}
        if device_id is not None:
            try:
                target["device_id"] = int(str(device_id))
            except (TypeError, ValueError):
                target["device_id"] = _bounded_audit_text(device_id)
        return target
    return None


def _bounded_audit_text(value: object) -> str:
    """Keep client-controlled audit identifiers from growing without bound."""

    text = str(value)
    if len(text) <= _MAX_AUDIT_IDENTIFIER_CHARS:
        return text
    return text[: _MAX_AUDIT_IDENTIFIER_CHARS - 1] + "…"


def _extract_result_request_id(result: Any) -> str | None:
    """Return the request ID from a tool result before FastMCP conversion."""
    if isinstance(result, ToolResult):
        return result.request_id
    if isinstance(result, dict):
        request_id = result.get("request_id")
        return request_id if isinstance(request_id, str) and request_id else None
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        request_id = result[1].get("request_id")
        return request_id if isinstance(request_id, str) and request_id else None
    return None


def _policy_result_for_error(error_code: str) -> str:
    """Classify policy decisions independently from invocation failures."""
    if error_code in _POLICY_ERROR_CODES:
        return "denied"
    return "not_evaluated"


def _audit_unavailable_error(request_id: str) -> ToolError:
    payload = structured_error_payload(
        code=ErrorCode.INTERNAL_ERROR.value,
        message="Audit trail is unavailable",
        request_id=request_id,
        details={
            "reason": "AUDIT_UNAVAILABLE",
            "next_action": "Restore the configured audit database, then retry.",
        },
    )
    return ToolError(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
