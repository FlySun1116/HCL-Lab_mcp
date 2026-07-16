"""Enforce a final UTF-8 byte budget for MCP tool results.

FastMCP exposes typed results twice: once as JSON ``TextContent`` for older
clients and once as ``structuredContent``.  Limiting only device console text
therefore cannot bound the actual protocol result.  This module measures the
final ``CallToolResult`` representation and rejects oversized results before
they cross the MCP boundary.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from functools import wraps
from typing import Any, cast

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, ContentBlock, TextContent

from h3c_hcl_mcp.domain.errors import ErrorCode
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.mcp.error_mapping import structured_error_payload


class OutputBudgetExceeded(Exception):
    """Raised internally when a converted MCP result exceeds its hard budget."""

    def __init__(self, actual_bytes: int) -> None:
        self.actual_bytes = actual_bytes
        super().__init__(f"MCP tool result requires {actual_bytes} bytes")


def compact_json(value: Any) -> str:
    """Serialize JSON deterministically without FastMCP's pretty-print overhead."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def call_tool_result_bytes(result: CallToolResult) -> int:
    """Return the exact UTF-8 size of a CallToolResult before JSON-RPC framing."""

    payload = result.model_dump_json(by_alias=True, exclude_none=True)
    return len(payload.encode("utf-8"))


def compact_tool_result(result: ToolResult) -> tuple[list[ContentBlock], dict[str, Any]]:
    """Build equivalent compact text and structured channels for a ToolResult."""

    structured = result.model_dump(mode="json")
    content: list[ContentBlock] = [TextContent(type="text", text=compact_json(structured))]
    return content, structured


def tool_result_bytes(result: ToolResult) -> int:
    """Measure a ToolResult exactly as it will appear in the MCP result envelope."""

    content, structured = compact_tool_result(result)
    return call_tool_result_bytes(
        CallToolResult(content=content, structuredContent=structured, isError=False)
    )


def output_too_large_error(
    *,
    request_id: str,
    max_bytes: int,
    actual_bytes: int,
) -> ToolError:
    """Create the stable public error used when a Tool result is oversized."""

    payload = structured_error_payload(
        code=ErrorCode.OUTPUT_TOO_LARGE.value,
        message="Tool result exceeds the configured output budget",
        request_id=request_id,
        details={
            "max_tool_result_bytes": max_bytes,
            "actual_bytes": actual_bytes,
            "next_action": "Narrow the request or increase server.max_tool_result_bytes.",
        },
    )
    return ToolError(compact_json(payload))


def with_output_budget(
    max_bytes: int,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Reject an oversized typed result inside the per-tool audit boundary."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, ToolResult):
                actual_bytes = tool_result_bytes(result)
                if actual_bytes > max_bytes:
                    raise output_too_large_error(
                        request_id=result.request_id,
                        max_bytes=max_bytes,
                        actual_bytes=actual_bytes,
                    )
            return result

        return wrapper

    return decorator


def compact_converted_result(converted: Any, max_bytes: int) -> Any:
    """Compact a FastMCP converted result and enforce the final hard budget."""

    if isinstance(converted, CallToolResult):
        actual_bytes = call_tool_result_bytes(converted)
        if actual_bytes > max_bytes:
            raise OutputBudgetExceeded(actual_bytes)
        return converted

    if isinstance(converted, tuple) and len(converted) == 2 and isinstance(converted[1], dict):
        structured = converted[1]
        content: list[ContentBlock] = [TextContent(type="text", text=compact_json(structured))]
        actual_bytes = call_tool_result_bytes(
            CallToolResult(content=content, structuredContent=structured, isError=False)
        )
        if actual_bytes > max_bytes:
            raise OutputBudgetExceeded(actual_bytes)
        return content, structured

    if isinstance(converted, Sequence) and not isinstance(converted, str | bytes | bytearray):
        content = cast(list[ContentBlock], list(converted))
        actual_bytes = call_tool_result_bytes(CallToolResult(content=content, isError=False))
        if actual_bytes > max_bytes:
            raise OutputBudgetExceeded(actual_bytes)
    return converted


def bounded_error_payload(payload: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Bound a structured ToolError while preserving code and request ID."""

    if _error_result_bytes(payload) <= max_bytes:
        return payload

    raw_error = payload.get("error")
    error = raw_error if isinstance(raw_error, dict) else {}
    code = str(error.get("code", ErrorCode.INTERNAL_ERROR.value))[:128]
    request_id = str(error.get("request_id", ""))[:128]
    message = str(error.get("message", "Tool error"))
    original_bytes = _error_result_bytes(payload)

    def candidate(message_value: str, *, include_details: bool) -> dict[str, Any]:
        bounded: dict[str, Any] = {
            "code": code,
            "message": message_value,
            "request_id": request_id,
        }
        if include_details:
            bounded.update({"truncated": True, "original_bytes": original_bytes})
        return {"error": bounded}

    compact = candidate(message, include_details=True)
    if _error_result_bytes(compact) <= max_bytes:
        return compact

    low = 0
    high = len(message)
    best = candidate("Tool error", include_details=False)
    while low <= high:
        middle = (low + high) // 2
        shortened = message[:middle] + ("…" if middle < len(message) else "")
        attempt = candidate(shortened, include_details=True)
        if _error_result_bytes(attempt) <= max_bytes:
            best = attempt
            low = middle + 1
        else:
            high = middle - 1
    return best


def _error_result_bytes(payload: dict[str, Any]) -> int:
    content: list[ContentBlock] = [TextContent(type="text", text=compact_json(payload))]
    return call_tool_result_bytes(CallToolResult(content=content, isError=True))
