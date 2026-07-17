"""Public FastMCP extension points for tool registration and invocation.

MCP 1.28 binds ``self.call_tool`` while constructing ``FastMCP``.  Subclassing
that public method therefore keeps protocol and direct calls on the same
boundary without mutating ``ToolManager`` internals.  Registration-time
wrapping similarly goes through the public ``add_tool`` method.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Sequence
from typing import Any, cast

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import FastMCP
from mcp.types import AnyFunction, ContentBlock, Icon, ToolAnnotations
from pydantic import ValidationError

from h3c_hcl_mcp.domain.audit import AuditEvent
from h3c_hcl_mcp.domain.errors import ErrorCode
from h3c_hcl_mcp.mcp.audit_middleware import (
    _audit_unavailable_error,
    _extract_target,
    with_audit,
)
from h3c_hcl_mcp.mcp.error_mapping import extract_structured_error, structured_error_payload
from h3c_hcl_mcp.mcp.output_budget import (
    OutputBudgetExceeded,
    bounded_error_payload,
    compact_converted_result,
    compact_json,
    output_too_large_error,
    with_output_budget,
)
from h3c_hcl_mcp.ports.audit_sink import AuditSink

logger = logging.getLogger(__name__)

_MAX_AUDIT_TOOL_NAME_CHARS = 256


class HCLFastMCP(FastMCP[Any]):
    """FastMCP variant with the project's stable call boundary.

    Tool functions are wrapped before FastMCP creates their schemas.  The
    wrappers use ``functools.wraps``, so public Tool schemas remain identical
    while audit and output-budget behavior no longer depend on private SDK
    registries.
    """

    def __init__(
        self,
        *args: Any,
        audit_sink: AuditSink | None = None,
        timeout_seconds: float | None = None,
        max_output_bytes: int | None = None,
        **kwargs: Any,
    ) -> None:
        if kwargs.get("tools") is not None:
            raise ValueError("HCLFastMCP tools must be registered through add_tool")
        self._hcl_audit_sink = audit_sink
        self._hcl_timeout_seconds = timeout_seconds
        self._hcl_max_output_bytes = max_output_bytes
        super().__init__(*args, **kwargs)

    def add_tool(
        self,
        fn: AnyFunction,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> None:
        """Register a Tool after applying the project-owned wrappers."""
        tool_name = name or fn.__name__
        wrapped = fn
        if self._hcl_max_output_bytes is not None:
            wrapped = with_output_budget(self._hcl_max_output_bytes)(wrapped)
        if self._hcl_audit_sink is not None:
            wrapped = with_audit(tool_name, self._hcl_audit_sink)(wrapped)
        super().add_tool(
            wrapped,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            icons=icons,
            meta=meta,
            structured_output=structured_output,
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        """Call a Tool with stable validation, timeout, and size errors."""
        start = time.monotonic()
        tool_schema = await self._tool_input_schema(name)
        if tool_schema is None:
            request_id = str(uuid.uuid4())
            payload = structured_error_payload(
                code=ErrorCode.INVALID_ARGUMENT.value,
                message="Unknown tool",
                request_id=request_id,
                details={"tool": _bounded_tool_name(name)},
            )
            if self._hcl_audit_sink is not None:
                await _audit_invalid_call(
                    audit_sink=self._hcl_audit_sink,
                    tool_name=name,
                    arguments=arguments,
                    request_id=request_id,
                    duration_ms=(time.monotonic() - start) * 1000,
                )
            if self._hcl_max_output_bytes is not None:
                payload = bounded_error_payload(payload, self._hcl_max_output_bytes)
            raise ToolError(compact_json(payload))

        async def invoke_tool() -> Sequence[ContentBlock] | dict[str, Any]:
            converted = await super(HCLFastMCP, self).call_tool(name, arguments)
            if self._hcl_max_output_bytes is not None:
                converted = cast(
                    Sequence[ContentBlock] | dict[str, Any],
                    compact_converted_result(converted, self._hcl_max_output_bytes),
                )
            return converted

        try:
            if self._hcl_timeout_seconds is None:
                return await invoke_tool()
            async with asyncio.timeout(self._hcl_timeout_seconds):
                return await invoke_tool()
        except TimeoutError:
            request_id = str(uuid.uuid4())
            payload = structured_error_payload(
                code=ErrorCode.TIMEOUT.value,
                message="Tool execution timed out",
                request_id=request_id,
                details={"timeout_seconds": self._hcl_timeout_seconds},
            )
            if self._hcl_audit_sink is not None:
                await _audit_invalid_call(
                    audit_sink=self._hcl_audit_sink,
                    tool_name=name,
                    arguments=arguments,
                    request_id=request_id,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error_code=ErrorCode.TIMEOUT,
                )
            if self._hcl_max_output_bytes is not None:
                payload = bounded_error_payload(payload, self._hcl_max_output_bytes)
            raise ToolError(compact_json(payload)) from None
        except OutputBudgetExceeded as error:
            request_id = str(uuid.uuid4())
            if self._hcl_audit_sink is not None:
                await _audit_invalid_call(
                    audit_sink=self._hcl_audit_sink,
                    tool_name=name,
                    arguments=arguments,
                    request_id=request_id,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error_code=ErrorCode.OUTPUT_TOO_LARGE,
                )
            raise output_too_large_error(
                request_id=request_id,
                max_bytes=self._hcl_max_output_bytes or error.actual_bytes,
                actual_bytes=error.actual_bytes,
            ) from None
        except ToolError as error:
            validation_error = _find_validation_error(error)
            if validation_error is None:
                structured = extract_structured_error(error)
                if structured is None or self._hcl_max_output_bytes is None:
                    raise
                payload = bounded_error_payload(
                    {"error": structured},
                    self._hcl_max_output_bytes,
                )
                raise ToolError(compact_json(payload)) from None

            request_id = str(uuid.uuid4())
            fields = _validation_fields(tool_schema, validation_error)
            payload = structured_error_payload(
                code=ErrorCode.INVALID_ARGUMENT.value,
                message="Invalid tool arguments",
                request_id=request_id,
                details={"fields": fields},
            )

            if self._hcl_audit_sink is not None:
                await _audit_invalid_call(
                    audit_sink=self._hcl_audit_sink,
                    tool_name=name,
                    arguments=arguments,
                    request_id=request_id,
                    duration_ms=(time.monotonic() - start) * 1000,
                )

            # Do not chain the Pydantic error: the low-level handler must only
            # expose our stable JSON and never Pydantic's documentation URL.
            if self._hcl_max_output_bytes is not None:
                payload = bounded_error_payload(payload, self._hcl_max_output_bytes)
            raise ToolError(compact_json(payload)) from None

    async def _tool_input_schema(self, tool_name: str) -> dict[str, Any] | None:
        """Return a registered Tool schema through FastMCP's public API."""
        for tool in await self.list_tools():
            if tool.name == tool_name:
                return tool.inputSchema
        return None


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
    tool_schema: dict[str, Any],
    validation_error: ValidationError,
) -> list[dict[str, Any]]:
    """Convert Pydantic errors into stable field-level MCP details."""
    properties: dict[str, Any] = {}
    raw_properties = tool_schema.get("properties")
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
                tool=(_bounded_tool_name(tool_name)),
                target=_extract_target(arguments),
                policy_result="not_evaluated",
                outcome="error",
                duration_ms=round(duration_ms, 2),
                error_code=error_code.value,
            )
        )
    except Exception as error:
        logger.error(
            "Failed to audit validation error for %s: %s",
            tool_name,
            type(error).__name__,
        )
        raise _audit_unavailable_error(request_id) from None


def _bounded_tool_name(tool_name: str) -> str:
    if len(tool_name) <= _MAX_AUDIT_TOOL_NAME_CHARS:
        return tool_name
    return tool_name[: _MAX_AUDIT_TOOL_NAME_CHARS - 1] + "…"
