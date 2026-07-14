"""Audit middleware — records every tool invocation to the audit sink.

Wraps tool functions to automatically record audit events for both
successful and failed calls.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any

from h3c_hcl_mcp.domain.audit import AuditEvent
from h3c_hcl_mcp.domain.errors import DomainError
from h3c_hcl_mcp.ports.audit_sink import AuditSink


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

            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except DomainError as e:
                error_code = e.code.value
                policy_result = "denied"
                raise
            except Exception:
                error_code = "INTERNAL_ERROR"
                policy_result = "denied"
                raise
            finally:
                duration_ms = (time.monotonic() - start) * 1000
                try:
                    event = AuditEvent(
                        event_id=str(uuid.uuid4()),
                        request_id=request_id,
                        caller=caller,
                        tool=tool_name,
                        target=_extract_target(kwargs),
                        policy_result=policy_result,
                        change_summary=change_summary,
                        duration_ms=round(duration_ms, 2),
                        error_code=error_code,
                    )
                    await audit_sink.append(event)
                except Exception:
                    pass  # Audit failure must not break the tool

        return wrapper

    return decorator


def _extract_target(kwargs: dict[str, Any]) -> dict[str, object] | None:
    """Extract target info from tool kwargs."""
    project_id = kwargs.get("project_id")
    device_id = kwargs.get("device_id")
    if project_id is not None:
        target: dict[str, object] = {"project_id": str(project_id)}
        if device_id is not None:
            target["device_id"] = int(device_id)  # type: ignore[call-overload]
        return target
    return None
