"""Normalize FastMCP/Pydantic argument validation failures.

FastMCP registers its low-level ``tools/call`` handler during construction.
Replacing ``FastMCP.call_tool`` afterwards therefore does not affect stdio
requests.  This module wraps ``ToolManager.call_tool`` instead: both the
registered protocol handler and direct/in-process calls pass that boundary.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import FastMCP
from pydantic import ValidationError

from h3c_hcl_mcp.domain.audit import AuditEvent
from h3c_hcl_mcp.domain.errors import ErrorCode
from h3c_hcl_mcp.mcp.audit_middleware import _extract_target
from h3c_hcl_mcp.mcp.error_mapping import extract_structured_error, structured_error_payload
from h3c_hcl_mcp.mcp.output_budget import (
    OutputBudgetExceeded,
    bounded_error_payload,
    compact_converted_result,
    compact_json,
    output_too_large_error,
)
from h3c_hcl_mcp.ports.audit_sink import AuditSink

logger = logging.getLogger(__name__)

_MAX_AUDIT_TOOL_NAME_CHARS = 256


def wrap_call_tool_with_validation(
    mcp: FastMCP,
    audit_sink: AuditSink | None = None,
    timeout_seconds: float | None = None,
    max_output_bytes: int | None = None,
) -> None:
    """Install validation normalization at the ToolManager call boundary.

    Args:
        mcp: FastMCP instance whose tool manager should be wrapped.
        audit_sink: Optional audit sink.  Validation happens before a tool
            function runs, so this boundary must record validation failures
            directly when auditing is enabled.
    """
    manager = mcp._tool_manager
    if getattr(manager, "_h3c_validation_wrapped", False):
        return

    original_call_tool = manager.call_tool

    async def wrapped_call_tool(
        name: str,
        arguments: dict[str, Any],
        context: Any = None,
        convert_result: bool = False,
    ) -> Any:
        start = time.monotonic()
        tool = manager.get_tool(name)
        if tool is None:
            request_id = str(uuid.uuid4())
            payload = structured_error_payload(
                code=ErrorCode.INVALID_ARGUMENT.value,
                message="Unknown tool",
                request_id=request_id,
                details={"tool": name},
            )
            if audit_sink is not None:
                await _audit_invalid_call(
                    audit_sink=audit_sink,
                    tool_name=name,
                    arguments=arguments,
                    request_id=request_id,
                    duration_ms=(time.monotonic() - start) * 1000,
                )
            if max_output_bytes is not None:
                payload = bounded_error_payload(payload, max_output_bytes)
            raise ToolError(compact_json(payload))

        async def invoke_tool() -> Any:
            result = await original_call_tool(
                name,
                arguments,
                context=context,
                convert_result=False,
            )
            if not convert_result:
                return result
            converted = tool.fn_metadata.convert_result(result)
            if max_output_bytes is not None:
                return compact_converted_result(converted, max_output_bytes)
            return converted

        try:
            if timeout_seconds is None:
                return await invoke_tool()
            async with asyncio.timeout(timeout_seconds):
                return await invoke_tool()
        except TimeoutError:
            request_id = str(uuid.uuid4())
            payload = structured_error_payload(
                code=ErrorCode.TIMEOUT.value,
                message="Tool execution timed out",
                request_id=request_id,
                details={"timeout_seconds": timeout_seconds},
            )
            if audit_sink is not None:
                await _audit_invalid_call(
                    audit_sink=audit_sink,
                    tool_name=name,
                    arguments=arguments,
                    request_id=request_id,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error_code=ErrorCode.TIMEOUT,
                )
            if max_output_bytes is not None:
                payload = bounded_error_payload(payload, max_output_bytes)
            raise ToolError(compact_json(payload)) from None
        except OutputBudgetExceeded as error:
            request_id = str(uuid.uuid4())
            if audit_sink is not None:
                await _audit_invalid_call(
                    audit_sink=audit_sink,
                    tool_name=name,
                    arguments=arguments,
                    request_id=request_id,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error_code=ErrorCode.OUTPUT_TOO_LARGE,
                )
            raise output_too_large_error(
                request_id=request_id,
                max_bytes=max_output_bytes or error.actual_bytes,
                actual_bytes=error.actual_bytes,
            ) from None
        except ToolError as error:
            validation_error = _find_validation_error(error)
            if validation_error is None:
                structured = extract_structured_error(error)
                if structured is None or max_output_bytes is None:
                    raise
                payload = bounded_error_payload({"error": structured}, max_output_bytes)
                raise ToolError(compact_json(payload)) from None

            request_id = str(uuid.uuid4())
            fields = _validation_fields(mcp, name, validation_error)
            payload = structured_error_payload(
                code=ErrorCode.INVALID_ARGUMENT.value,
                message="Invalid tool arguments",
                request_id=request_id,
                details={"fields": fields},
            )

            if audit_sink is not None:
                await _audit_invalid_call(
                    audit_sink=audit_sink,
                    tool_name=name,
                    arguments=arguments,
                    request_id=request_id,
                    duration_ms=(time.monotonic() - start) * 1000,
                )

            # Do not chain the Pydantic error: the low-level handler must only
            # expose our stable JSON and never Pydantic's documentation URL.
            if max_output_bytes is not None:
                payload = bounded_error_payload(payload, max_output_bytes)
            raise ToolError(compact_json(payload)) from None

    manager.call_tool = wrapped_call_tool  # type: ignore[method-assign]
    manager._h3c_validation_wrapped = True  # type: ignore[attr-defined]


def _find_validation_error(error: BaseException) -> ValidationError | None:
    """Find the original Pydantic error through FastMCP's ToolError chain."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ValidationError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _validation_fields(
    mcp: FastMCP,
    tool_name: str,
    validation_error: ValidationError,
) -> list[dict[str, Any]]:
    """Convert Pydantic errors into stable field-level MCP details."""
    properties: dict[str, Any] = {}
    tool = mcp._tool_manager.get_tool(tool_name)
    if tool is not None:
        schema = tool.fn_metadata.arg_model.model_json_schema()
        raw_properties = schema.get("properties")
        if isinstance(raw_properties, dict):
            properties = raw_properties

    fields: list[dict[str, Any]] = []
    for item in validation_error.errors(include_url=False, include_input=False):
        location = item.get("loc", ())
        field_name = ".".join(str(part) for part in location) or "unknown"
        field_error: dict[str, Any] = {
            "field": field_name,
            "message": str(item.get("msg", "Invalid value")),
            "type": str(item.get("type", "validation_error")),
        }

        root_field = str(location[0]) if location else ""
        field_schema = properties.get(root_field)
        if isinstance(field_schema, dict):
            allowed = field_schema.get("enum")
            if isinstance(allowed, list):
                field_error["allowed"] = allowed
            for schema_key in (
                "minimum",
                "maximum",
                "exclusiveMinimum",
                "exclusiveMaximum",
                "minLength",
                "maxLength",
                "pattern",
            ):
                if schema_key in field_schema:
                    field_error[schema_key] = field_schema[schema_key]
        fields.append(field_error)

    return fields or [
        {
            "field": "unknown",
            "message": "Invalid value",
            "type": "validation_error",
        }
    ]


async def _audit_invalid_call(
    *,
    audit_sink: AuditSink,
    tool_name: str,
    arguments: dict[str, Any],
    request_id: str,
    duration_ms: float,
    error_code: ErrorCode = ErrorCode.INVALID_ARGUMENT,
) -> None:
    """Record an invalid call that occurs before a tool function runs."""
    try:
        await audit_sink.append(
            AuditEvent(
                event_id=str(uuid.uuid4()),
                request_id=request_id,
                caller="mcp-client",
                tool=(
                    tool_name
                    if len(tool_name) <= _MAX_AUDIT_TOOL_NAME_CHARS
                    else tool_name[: _MAX_AUDIT_TOOL_NAME_CHARS - 1] + "…"
                ),
                target=_extract_target(arguments),
                policy_result="not_evaluated",
                outcome="error",
                duration_ms=round(duration_ms, 2),
                error_code=error_code.value,
            )
        )
    except Exception as error:
        logger.warning("Failed to audit validation error for %s: %s", tool_name, error)
